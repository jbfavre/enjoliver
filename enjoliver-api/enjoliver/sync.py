"""
Sync the matchbox configuration
"""
import json
import logging
import os
import re
import time
from ipaddress import IPv4Interface

import requests
from werkzeug.contrib.cache import SimpleCache, NullCache

from enjoliver import schedulerv2, generator
from enjoliver.configs import EnjoliverConfig

EC = EnjoliverConfig(importer=__file__)

logger = logging.getLogger(__name__)


class ConfigSyncSchedules(object):
    __name__ = "ConfigSyncSchedules"
    sub_ips = EC.sub_ips
    range_nb_ips = EC.range_nb_ips
    skip_ips = EC.skip_ips

    def __init__(self, api_uri: str, matchbox_path: str, ignition_dict: dict, extra_selector_dict=None):
        """
        :param api_uri: http://1.1.1.1:5000
        :param matchbox_path: /var/lib/matchbox
        :param ignition_dict: ignition.yaml
        """
        self.api_uri = api_uri
        os.environ["API_URI"] = self.api_uri
        self.matchbox_path = matchbox_path
        self.ignition_dict = ignition_dict
        self._reporting_ignitions()
        self.extra_selector = extra_selector_dict if extra_selector_dict else {}
        # inMemory cache for http queries
        if EC.sync_cache_ttl > 0:
            self._cache_query = SimpleCache(default_timeout=EC.sync_cache_ttl)
        else:
            self._cache_query = NullCache()

    def _reporting_ignitions(self):
        for k, v in self.ignition_dict.items():
            f = "%s/ignition/%s.yaml" % (self.matchbox_path, v)
            if os.path.isfile(f) is False:
                logger.error("%s:%s -> %s is not here" % (k, v, f))
                raise IOError(f)
            with open(f, 'rb') as ignition_file:
                blob = ignition_file.read()
            data = {v: blob.decode()}
            url = "%s/ignition/version/%s" % (self.api_uri, v)
            try:
                req = requests.post(url, data=json.dumps(data))
                req.close()
                response = json.loads(req.content.decode())
                logger.info("%s:%s -> %s is here content reported: %s" % (k, v, f, response))
            except requests.exceptions.ConnectionError as e:
                logger.error("%s:%s -> %s is here content NOT reported: %s" % (k, v, f, e))

    @staticmethod
    def get_dns_attr(fqdn: str):
        """
        TODO: Use LLDP to avoid vendor specific usage
        :param fqdn: e.g: r13-srv3.dc-1.foo.bar.cr
        :return:
        """
        d = {
            "shortname": "",
            "dc": "",
            "domain": "",
            "rack": "",
            "pos": "",
        }
        s = fqdn.split(".")
        d["shortname"] = s[0]
        try:
            d["dc"] = s[1]
        except IndexError:
            logger.error("IndexError %s[1] after split(.)" % fqdn)
            return d
        d["domain"] = ".".join(s[1:])
        try:
            rack, pos = s[0].split("-")
            d["rack"] = re.sub("[^0-9]+", "", rack)
            d["pos"] = re.sub("[^0-9]+", "", pos)
        except ValueError:
            logger.error("error during the split rack/pos %s" % s[0])
        return d

    @staticmethod
    def _cni_ipam(host_cidrv4: str, host_gateway: str):
        """
        see: https://github.com/containernetworking/cni/blob/master/SPEC.md#ip-allocation
        see: https://github.com/containernetworking/plugins/tree/master/plugins/ipam/host-local
        With the class variables provide a way to generate a static host-local ipam
        :param host_cidrv4: an host IP with its CIDR prefixlen, eg: '10.0.0.42/8'
        :param host_gateway: an host IP for the gateway, eg: '10.0.0.1'
        :return: dict
        """
        interface = IPv4Interface(host_cidrv4)
        subnet = interface.network

        try:
            assert 0 <= ConfigSyncSchedules.sub_ips <= 256
            assert (lambda x: x & (x-1) == 0)(ConfigSyncSchedules.sub_ips)
        except AssertionError:
            raise ValueError('sub_ips must be a power of two, in [0, 256] interval')

        if ConfigSyncSchedules.sub_ips > 0:
            ip_last_decimal_field = int(str(interface.ip).split('.')[-1])
            interface = IPv4Interface(
                interface.network.network_address +
                ip_last_decimal_field * ConfigSyncSchedules.sub_ips
            )

        range_start = interface.ip + ConfigSyncSchedules.skip_ips
        range_end = range_start + ConfigSyncSchedules.range_nb_ips
        ipam = {
            "type": "host-local",
            "subnet": "%s" % (str(subnet)),
            "rangeStart": str(range_start),
            "rangeEnd": str(range_end),
            "gateway": host_gateway,
            "routes": [
                {"dst": "%s/32" % EC.perennial_local_host_ip, "gw": str(IPv4Interface(host_cidrv4).ip)},
                {"dst": "0.0.0.0/0"},
            ],
            "dataDir": "/var/lib/cni/networks"
        }
        return ipam

    @staticmethod
    def get_extra_selectors(extra_selectors: dict):
        """
        Extra selectors are passed to Matchbox
        :param extra_selectors: dict
        :return:
        """
        if extra_selectors:
            if type(extra_selectors) is dict:
                logger.debug("extra selectors: %s" % extra_selectors)
                return extra_selectors

            logger.error("invalid extra selectors: %s" % extra_selectors)
            raise TypeError("%s %s is not type dict" % (extra_selectors, type(extra_selectors)))

        logger.debug("no extra selectors")
        return {}

    @property
    def etcd_member_ip_list(self):
        return self._query_ip_list(schedulerv2.ScheduleRoles.etcd_member)

    @property
    def kubernetes_control_plane_ip_list(self):
        return self._query_ip_list(schedulerv2.ScheduleRoles.kubernetes_control_plane)

    @property
    def kubernetes_nodes_ip_list(self):
        return self._query_ip_list(schedulerv2.ScheduleRoles.kubernetes_node)

    @staticmethod
    def order_http_uri(ips: list, ec_value: int, secure=False):
        ips.sort()
        e = ["http{}://%s:%d".format("s" if secure else "") % (k, ec_value) for k in ips]
        return e

    @staticmethod
    def order_etcd_named(ips: list, ec_value: int, secure=False):
        ips.sort()
        e = ["%s=http{}://%s:%d".format("s" if secure else "") % (k, k, ec_value) for k in ips]
        return ",".join(e)

    @property
    def kubernetes_etcd_initial_cluster(self):
        return self.order_etcd_named(self.etcd_member_ip_list, EC.kubernetes_etcd_peer_port, secure=True)

    @property
    def vault_etcd_initial_cluster(self):
        return self.order_etcd_named(self.etcd_member_ip_list, EC.vault_etcd_peer_port, secure=True)

    @property
    def fleet_etcd_initial_cluster(self):
        return self.order_etcd_named(self.etcd_member_ip_list, EC.fleet_etcd_peer_port, secure=True)

    @property
    def kubernetes_etcd_member_client_uri_list(self):
        return self.order_http_uri(self.etcd_member_ip_list, EC.kubernetes_etcd_client_port, secure=True)

    @property
    def vault_etcd_member_client_uri_list(self):
        return self.order_http_uri(self.etcd_member_ip_list, EC.vault_etcd_client_port, secure=True)

    @property
    def fleet_etcd_member_client_uri_list(self):
        return self.order_http_uri(self.etcd_member_ip_list, EC.fleet_etcd_client_port, secure=True)

    @property
    def kubernetes_etcd_member_peer_uri_list(self):
        return self.order_http_uri(self.etcd_member_ip_list, EC.kubernetes_etcd_peer_port, secure=True)

    @property
    def vault_etcd_member_peer_uri_list(self):
        return self.order_http_uri(self.etcd_member_ip_list, EC.vault_etcd_peer_port, secure=True)

    @property
    def fleet_etcd_member_peer_uri_list(self):
        return self.order_http_uri(self.etcd_member_ip_list, EC.fleet_etcd_peer_port, secure=True)

    @property
    def kubernetes_control_plane(self):
        return self.order_http_uri(self.kubernetes_control_plane_ip_list, EC.kubernetes_apiserver_insecure_port)

    @staticmethod
    def compute_disks_size(disks: list):
        total_size_gb = 0
        if not disks:
            return "inMemory"

        for d in disks:
            total_size_gb += d["size-bytes"] >> 30
        ladder = list(EC.disks_ladder_gb.items())
        ladder.sort(key=lambda x: x[1])
        for k, v in ladder:
            if total_size_gb < v:
                return k

        return ladder[-1][0]

    def produce_matchbox_data(
            self,
            marker: str,
            i: int,
            m: dict,
            automatic_name: str,
            update_extra_metadata=None
    ):
        fqdn = automatic_name
        try:
            if m["fqdn"]:
                fqdn = m["fqdn"]
        except KeyError as e:
            logger.warning("%s for %s" % (e, m["mac"]))

        etc_hosts = [k for k in EC.etc_hosts]
        dns_attr = self.get_dns_attr(fqdn)
        etc_hosts.append("127.0.1.1 %s %s" % (fqdn, dns_attr["shortname"]))
        cni_attr = self._cni_ipam(m["cidrv4"], m["gateway"])
        extra_metadata = {
            "etc_hosts": etc_hosts,
            # Etcd
            "etcd_name": m["ipv4"],

            "kubernetes_etcd_initial_cluster": self.kubernetes_etcd_initial_cluster,
            "vault_etcd_initial_cluster": self.vault_etcd_initial_cluster,
            "fleet_etcd_initial_cluster": self.fleet_etcd_initial_cluster,

            "kubernetes_etcd_initial_advertise_peer_urls": "https://%s:%d" % (
                m["ipv4"], EC.kubernetes_etcd_peer_port),
            "vault_etcd_initial_advertise_peer_urls": "https://%s:%d" % (
                m["ipv4"], EC.vault_etcd_peer_port),
            "fleet_etcd_initial_advertise_peer_urls": "https://%s:%d" % (
                m["ipv4"], EC.fleet_etcd_peer_port),

            "kubernetes_etcd_member_client_uri_list": ",".join(self.kubernetes_etcd_member_client_uri_list),
            "vault_etcd_member_client_uri_list": ",".join(self.vault_etcd_member_client_uri_list),
            "fleet_etcd_member_client_uri_list": ",".join(self.fleet_etcd_member_client_uri_list),

            "kubernetes_etcd_data_dir": EC.kubernetes_etcd_data_dir,
            "vault_etcd_data_dir": EC.vault_etcd_data_dir,
            "fleet_etcd_data_dir": EC.fleet_etcd_data_dir,

            "kubernetes_etcd_client_port": EC.kubernetes_etcd_client_port,
            "vault_etcd_client_port": EC.vault_etcd_client_port,
            "fleet_etcd_client_port": EC.fleet_etcd_client_port,

            "kubernetes_etcd_advertise_client_urls": "https://%s:%d" % (
                m["ipv4"], EC.kubernetes_etcd_client_port),
            "vault_etcd_advertise_client_urls": "https://%s:%d" % (
                m["ipv4"], EC.vault_etcd_client_port),
            "fleet_etcd_advertise_client_urls": "https://%s:%d" % (
                m["ipv4"], EC.fleet_etcd_client_port),

            # Kubernetes
            "kubernetes_apiserver_insecure_port": EC.kubernetes_apiserver_insecure_port,
            "kubernetes_node_ip": "%s" % m["ipv4"],
            "kubernetes_node_name": "%s" % m["ipv4"] if fqdn == automatic_name else fqdn,
            "kubernetes_service_cluster_ip_range": EC.kubernetes_service_cluster_ip_range,

            # Vault are located with the etcd members
            "vault_ip_list": ",".join(self.etcd_member_ip_list),
            "vault_port": EC.vault_port,

            "kubelet_healthz_port": EC.kubelet_healthz_port,

            "etcd_member_kubernetes_control_plane_ip_list": ",".join(self.etcd_member_ip_list),
            "etcd_member_kubernetes_control_plane_ip": self.etcd_member_ip_list,

            "hyperkube_image_url": EC.hyperkube_image_url,
            "cephtools_image_url": EC.cephtools_image_url,
            # IPAM
            "cni": json.dumps(cni_attr, sort_keys=True),
            "network": {
                "cidrv4": m["cidrv4"],
                "gateway": m["gateway"],
                "ip": m["ipv4"],
                "subnet": cni_attr["subnet"],
                "perennial_host_ip": EC.perennial_local_host_ip,
                "ip_or_fqdn": fqdn if EC.sync_replace_ip_by_fqdn else m["ipv4"],
            },
            # host
            "hostname": dns_attr["shortname"],
            "dns_attr": dns_attr,
            "nameservers": " ".join(EC.nameservers),
            "ntp": " ".join(EC.ntp),
            "fallbackntp": " ".join(EC.fallbackntp),
            "vault_polling_sec": EC.vault_polling_sec,
            "lifecycle_update_polling_sec": EC.lifecycle_update_polling_sec,
            "disk_profile": self.compute_disks_size(m["disks"]),

        }
        selector = {"mac": m["mac"]}
        selector.update(self.get_extra_selectors(self.extra_selector))
        if update_extra_metadata:
            extra_metadata.update(update_extra_metadata)
        gen = generator.Generator(
            api_uri=self.api_uri,
            group_id="%s-%d" % (marker, i),  # one per machine
            profile_id=marker,  # link to ignition
            name=marker,
            ignition_id="%s.yaml" % self.ignition_dict[marker],
            matchbox_path=self.matchbox_path,
            selector=selector,
            extra_metadata=extra_metadata,
        )
        gen.dumps()

    def etcd_member_kubernetes_control_plane(self):
        marker = self.etcd_member_kubernetes_control_plane.__name__
        roles = schedulerv2.EtcdMemberKubernetesControlPlane.roles

        machine_roles = self._query_roles(*roles)
        for i, m in enumerate(machine_roles):
            update_md = {
                # Roles
                "roles": ",".join(roles),
                # Etcd Members
                "kubernetes_etcd_member_peer_uri_list": ",".join(self.kubernetes_etcd_member_peer_uri_list),
                "vault_etcd_member_peer_uri_list": ",".join(self.vault_etcd_member_peer_uri_list),
                "fleet_etcd_member_peer_uri_list": ",".join(self.fleet_etcd_member_peer_uri_list),

                "kubernetes_etcd_peer_port": EC.kubernetes_etcd_peer_port,
                "vault_etcd_peer_port": EC.vault_etcd_peer_port,
                "fleet_etcd_peer_port": EC.fleet_etcd_peer_port,

                # K8s Control Plane
                "kubernetes_apiserver_count": len(machine_roles),
                "kubernetes_apiserver_insecure_bind_address": EC.kubernetes_apiserver_insecure_bind_address,
            }
            self.produce_matchbox_data(
                marker=marker,
                i=i,
                m=m,
                automatic_name="cp-%d-%s" % (i, m["ipv4"].replace(".", "-")),
                update_extra_metadata=update_md,
            )
        logger.info("synced %d" % len(machine_roles))
        return len(machine_roles)

    def kubernetes_nodes(self):
        marker = self.kubernetes_nodes.__name__
        roles = schedulerv2.KubernetesNode.roles

        machine_roles = self._query_roles(*roles)
        for i, m in enumerate(machine_roles):
            update_md = {
                # Roles
                "roles": ",".join(roles),
            }
            self.produce_matchbox_data(
                marker=marker,
                i=i,
                m=m,
                automatic_name="no-%d-%s" % (i, m["ipv4"].replace(".", "-")),
                update_extra_metadata=update_md,
            )
        logger.info("synced %d" % len(machine_roles))
        return len(machine_roles)

    def notify(self):
        """
        TODO if we need to notify the API for any reason
        :return:
        """
        req = requests.post("%s/sync-notify" % self.api_uri)
        req.close()
        logger.debug("notified API")

    def apply(self, nb_try=2, seconds_sleep=0):
        logger.info("start syncing...")
        for i in range(nb_try):
            try:
                nb = self.etcd_member_kubernetes_control_plane()
                nb += self.kubernetes_nodes()
                self.notify()
                return nb
            except Exception as e:
                logger.error("fail to apply the sync %s %s" % (type(e), e))
                if i + 1 == nb_try:
                    raise

            logger.warning("retry %d/%d in %d s" % (i + 1, nb_try, seconds_sleep))
            time.sleep(seconds_sleep)
        raise RuntimeError("fail to apply after %d try" % nb_try)

    def _query_roles(self, *roles):
        roles = "&".join(roles)
        url = "/scheduler/%s" % roles
        logger.debug("roles='%s'" % roles)
        data = self._cache_query.get(url)
        if data is None:
            # not in cache or evicted
            logger.debug("cache is empty for %s" % url)
            req = requests.get("%s%s" % (self.api_uri, url))
            data = json.loads(req.content.decode())
            req.close()
            data.sort(key=lambda k: k["mac"])
            self._cache_query.set(url, data)
        return data

    def _query_ip_list(self, role):
        logger.debug("role='%s'" % role)
        url = "/scheduler/ip-list/%s" % role
        data = self._cache_query.get(url)
        if data is None:
            # not in cache or evicted
            logger.debug("cache is empty for %s" % url)
            req = requests.get("%s%s" % (self.api_uri, url))
            data = json.loads(req.content.decode())
            req.close()
            data.sort()
            self._cache_query.set(url, data)
        return data
