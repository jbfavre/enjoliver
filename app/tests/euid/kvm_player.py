import abc
import json
import multiprocessing
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib2

import datetime

from app import generator, api


@unittest.skipIf(os.geteuid() != 0,
                 "TestKVMDiscovery need privilege")
class KernelVirtualMachinePlayer(unittest.TestCase):
    """
    This class is used by all Kernel Virtual Machine testing suite
    Override the setUpClass by selecting your custom environment with the following catalog:
    >>> @classmethod
    >>> def setUpClass(cls):
    >>>     cls.check_requirements()
    >>>     cls.set_api()
    >>>     cls.set_bootcfg()
    >>>     cls.set_dnsmasq()
    >>>     cls.set_lldp()
    >>>     cls.set_rack0()
    >>>     cls.pause(5)
    Note: you may use 'reset -q' because of Link Layer Discovery Protocol Container's
    """
    __name__ = "KernelVirtualMachinePlayer"

    p_bootcfg = multiprocessing.Process
    p_dnsmasq = multiprocessing.Process
    p_api = multiprocessing.Process
    p_lldp = multiprocessing.Process
    p_list = []
    gen = generator.Generator

    euid_path = "%s" % os.path.dirname(os.path.abspath(__file__))
    tests_path = "%s" % os.path.split(euid_path)[0]
    app_path = os.path.split(tests_path)[0]
    project_path = os.path.split(app_path)[0]
    bootcfg_path = "%s/bootcfg" % project_path
    assets_path = "%s/bootcfg/assets" % project_path

    test_bootcfg_path = "%s/test_bootcfg" % tests_path

    bootcfg_port = int(os.getenv("BOOTCFG_PORT", "8080"))

    bootcfg_address = "0.0.0.0:%d" % bootcfg_port
    bootcfg_endpoint = "http://localhost:%d" % bootcfg_port

    api_port = int(os.getenv("API_PORT", "5000"))

    api_host = "172.20.0.1"
    api_endpoint = "http://%s:%d" % (api_host, api_port)

    dev_null = open("/dev/null", "w")

    kvm_sleep_between_node = 3

    @staticmethod
    def pause(t=600):
        """
        Sleep for eventual side testing or tests/s.sh ...
        :param t: 10 minutes
        :return: None
        """
        try:
            os.write(2, "\r==> sleep %d...\n\r" % t)
            time.sleep(t)
        except KeyboardInterrupt:
            pass
        finally:
            os.write(2, "\r==> sleep finish\n\r")

    @staticmethod
    def process_target_bootcfg():
        cmd = [
            "%s/bootcfg_dir/bootcfg" % KernelVirtualMachinePlayer.tests_path,
            "-data-path", "%s" % KernelVirtualMachinePlayer.test_bootcfg_path,
            "-assets-path", "%s" % KernelVirtualMachinePlayer.assets_path,
            "-address", "%s" % KernelVirtualMachinePlayer.bootcfg_address,
            "-log-level", "debug"
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execve(cmd[0], cmd, os.environ)

    @staticmethod
    def process_target_api():
        api.cache.clear()
        cmd = [
            "%s/env/bin/gunicorn" % KernelVirtualMachinePlayer.project_path,
            "--chdir",
            "%s" % KernelVirtualMachinePlayer.app_path,
            "api:app",
            "-b",
            "0.0.0.0:5000",
            "--log-level",
            "debug"
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (os.getpid(), " ".join(cmd)))
        os.execve(cmd[0], cmd, os.environ)

    @staticmethod
    def process_target_dnsmasq():
        cmd = [
            "%s/rkt_dir/rkt" % KernelVirtualMachinePlayer.tests_path,
            "--local-config=%s" % KernelVirtualMachinePlayer.tests_path,
            "--mount",
            "volume=config,target=/etc/dnsmasq.conf",
            "--mount",
            "volume=resolv,target=/etc/resolv.conf",
            "run",
            "quay.io/coreos/dnsmasq:v0.3.0",
            "--insecure-options=all",
            "--net=host",
            "--interactive",
            "--set-env=TERM=%s" % os.getenv("TERM", "xterm"),
            "--uuid-file-save=/tmp/dnsmasq.uuid",
            "--volume",
            "resolv,kind=host,source=/etc/resolv.conf",
            "--volume",
            "config,kind=host,source=%s/dnsmasq-rack0.conf" % KernelVirtualMachinePlayer.tests_path
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execve(cmd[0], cmd, os.environ)
        os._exit(2)

    @staticmethod
    def fetch_lldpd():
        cmd = [
            "%s/rkt_dir/rkt" % KernelVirtualMachinePlayer.tests_path,
            "--local-config=%s" % KernelVirtualMachinePlayer.tests_path,
            "fetch",
            "--insecure-options=all",
            "%s/lldp/serve/static-aci-lldp-0.aci" % KernelVirtualMachinePlayer.assets_path]
        assert subprocess.call(cmd) == 0

    @staticmethod
    def process_target_lldpd():
        cmd = [
            "%s/rkt_dir/rkt" % KernelVirtualMachinePlayer.tests_path,
            "--local-config=%s" % KernelVirtualMachinePlayer.tests_path,
            "run",
            "static-aci-lldp",
            "--insecure-options=all",
            "--net=host",
            "--interactive",
            "--set-env=TERM=%s" % os.getenv("TERM", "xterm"),
            "--exec",
            "/usr/sbin/lldpd",
            "--",
            "-dd"]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execve(cmd[0], cmd, os.environ)
        os._exit(2)  # Should not happen

    @staticmethod
    def dns_masq_running():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = 1
        for i in xrange(120):
            result = sock.connect_ex(('172.20.0.1', 53))
            if result == 0:
                break
            time.sleep(0.5)
            if i % 10 == 0:
                os.write(1, "DNSMASQ still NOT ready\n\r")
        assert result == 0
        os.write(1, "DNSMASQ ready\n\r")
        sys.stdout.flush()

    @classmethod
    def check_requirements(cls):
        if os.geteuid() != 0:
            raise RuntimeError("Need to be root EUID==%d" % os.geteuid())

        cls.clean_sandbox()

        if os.path.isfile("%s/rkt_dir/rkt" % KernelVirtualMachinePlayer.tests_path) is False or \
                        os.path.isfile("%s/bootcfg_dir/bootcfg" % KernelVirtualMachinePlayer.tests_path) is False:
            os.write(2, "Call 'make' as user for:\n"
                        "- %s/rkt_dir/rkt\n" % KernelVirtualMachinePlayer.tests_path +
                     "- %s/bootcfg_dir/bootcfg\n" % KernelVirtualMachinePlayer.tests_path)
            exit(2)
        os.write(1, "PPID -> %s\n" % os.getpid())

    @classmethod
    def set_bootcfg(cls):
        cls.p_bootcfg = multiprocessing.Process(target=KernelVirtualMachinePlayer.process_target_bootcfg,
                                                name="bootcfg")
        cls.p_bootcfg.start()
        time.sleep(0.5)
        assert cls.p_bootcfg.is_alive() is True
        cls.p_list.append(cls.p_bootcfg)

    @classmethod
    def set_rack0(cls):
        ret = subprocess.call([
            "%s/rkt_dir/rkt" % KernelVirtualMachinePlayer.tests_path,
            "--local-config=%s" % KernelVirtualMachinePlayer.tests_path,
            "run",
            "quay.io/coreos/dnsmasq:v0.3.0",
            "--insecure-options=all",
            "--net=rack0",
            "--interactive",
            "--set-env=TERM=%s" % os.getenv("TERM", "xterm"),
            "--exec",
            "/bin/true"])
        os.write(1, "\rBridge w/ iptables creation exitcode:%d\n\r" % ret)
        assert subprocess.call(["ip", "link", "show", "rack0"]) == 0

    @classmethod
    def set_dnsmasq(cls):
        cls.p_dnsmasq = multiprocessing.Process(target=KernelVirtualMachinePlayer.process_target_dnsmasq,
                                                name="dnsmasq")
        cls.p_dnsmasq.start()
        time.sleep(0.5)
        assert cls.p_dnsmasq.is_alive() is True
        cls.dns_masq_running()
        cls.p_list.append(cls.p_dnsmasq)

    @classmethod
    def set_api(cls):
        cls.p_api = multiprocessing.Process(target=KernelVirtualMachinePlayer.process_target_api, name="api")
        cls.p_api.start()
        time.sleep(0.5)
        assert cls.p_api.is_alive() is True
        cls.p_list.append(cls.p_api)

    @classmethod
    def set_lldp(cls):
        cls.fetch_lldpd()
        cls.p_lldp = multiprocessing.Process(target=KernelVirtualMachinePlayer.process_target_lldpd, name="lldp")
        cls.p_lldp.start()
        time.sleep(0.5)
        assert cls.p_lldp.is_alive() is True
        cls.p_list.append(cls.p_lldp)

    @classmethod
    def setUpClass(cls):
        raise NotImplementedError

    @classmethod
    def tearDownClass(cls):
        for p in cls.p_list:
            if p.is_alive():
                os.write(1, "\n\rTERM -> %d %s\n\r" % (p.pid, p.name))
                p.terminate()
                p.join(timeout=4)
                os.write(1, "\rEND -> %d %s\n\r" % (p.exitcode, p.name))

        subprocess.call([
            "%s/rkt_dir/rkt" % KernelVirtualMachinePlayer.tests_path,
            "--local-config=%s" % KernelVirtualMachinePlayer.tests_path,
            "gc",
            "--grace-period=0s"])
        cls.pause(5)
        cls.write_ending(cls.__name__)

    @staticmethod
    def write_ending(message):
        with open("/tmp/unittest.end", "a") as f:
            f.write("%s %s\n" % (datetime.datetime.now(), message))

    @staticmethod
    def clean_sandbox():
        dirs = ["%s/%s" % (KernelVirtualMachinePlayer.test_bootcfg_path, k)
                for k in ("profiles", "groups")]
        for d in dirs:
            for f in os.listdir(d):
                if ".json" in f:
                    os.write(1, "\r-> remove %s\n\r" % f)
                    os.remove("%s/%s" % (d, f))

    def api_healthz(self, first=True):
        try:
            request = urllib2.urlopen("%s/healthz" % self.api_endpoint)
            response_body = request.read()
            request.close()
            health = json.loads(response_body)
            self.assertTrue(health["global"])
        except Exception as e:
            os.write(2, "\r%s: %s\n\r" % (self.api_healthz.__name__, e.message))
            if first is True:
                self.api_healthz(False)

    def setUp(self):
        self.clean_sandbox()
        self.api_healthz()

    def virsh(self, cmd, assertion=False, v=None):
        if v is not None:
            os.write(1, "\r-> " + " ".join(cmd) + "\n\r")
            sys.stdout.flush()
        ret = subprocess.call(cmd, stdout=v, stderr=v)
        if assertion is True and ret != 0:
            raise RuntimeError("\"%s\"" % " ".join(cmd))

    def fetch_discovery_interfaces(self):
        request = urllib2.urlopen("%s/discovery/interfaces" % self.api_endpoint)
        response_body = request.read()
        request.close()
        self.assertEqual(request.code, 200)
        interfaces = json.loads(response_body)
        return interfaces

    def fetch_discovery(self):
        request = urllib2.urlopen("%s/discovery" % self.api_endpoint)
        response_body = request.read()
        request.close()
        self.assertEqual(request.code, 200)
        disco_data = json.loads(response_body)
        return disco_data

    def kvm_restart_off_machines(self, to_start, tries=90):
        for j in xrange(tries):
            if len(to_start) == 0:
                break

            for i, m in enumerate(to_start):
                start = ["virsh", "start", "%s" % m]
                try:
                    self.virsh(start, assertion=True), os.write(1, "\r")
                    to_start.pop(i)
                    time.sleep(4)

                except RuntimeError:
                    # virsh raise this
                    pass

            time.sleep(1)
        self.assertEqual(len(to_start), 0)

    def etcd_endpoint_health(self, ips, tries=15):
        for t in xrange(tries):
            for i, ip in enumerate(ips):
                try:
                    endpoint = "http://%s:2379/health" % ip
                    request = urllib2.urlopen(endpoint)
                    response_body = json.loads(request.read())
                    request.close()
                    os.write(1, "\r-> RESULT %s %s\n\r" % (endpoint, response_body))
                    sys.stdout.flush()
                    if response_body == {u"health": u"true"}:
                        ips.pop(i)
                        os.write(1, "\r-> REMAIN %s\n\r" % str(ips))

                except urllib2.URLError:
                    os.write(2, "\r-> NOT READY %s\n\r" % ip)
                    time.sleep(6)
        self.assertEqual(len(ips), 0)

    def etcd_member_len(self, ip, members, tries=30):
        result = {}
        for t in xrange(tries):
            try:
                endpoint = "http://%s:2379/v2/members" % ip
                request = urllib2.urlopen(endpoint)
                content = request.read()
                request.close()
                result = json.loads(content)
                os.write(1, "\r-> RESULT %s %s\n\r" % (endpoint, result))
                sys.stdout.flush()
                if len(result["members"]) == members:
                    break

            except urllib2.URLError:
                os.write(2, "\r-> NOT READY %s\n\r" % ip)
                time.sleep(10)

        self.assertEqual(len(result["members"]), members)

    def etcd_member_k8s_minions(self, ip, nodes_nb, tries=30):
        result = {}
        for t in xrange(tries):
            try:
                endpoint = "http://%s:2379/v2/keys/registry/minions" % ip
                request = urllib2.urlopen(endpoint)
                content = request.read()
                request.close()
                result = json.loads(content)
                sys.stdout.flush()
                if result and len(result["node"]["nodes"]) == nodes_nb:
                    break

            except urllib2.URLError:
                os.write(2, "\r-> NOT READY %s\n\r" % ip)
                time.sleep(10)

        self.assertEqual(len(result["node"]["nodes"]), nodes_nb)

    def k8s_api_health(self, ips, tries=90):
        for t in xrange(tries):
            for i, ip in enumerate(ips):
                try:
                    endpoint = "http://%s:8080/healthz" % ip
                    request = urllib2.urlopen(endpoint)
                    response_body = request.read()
                    request.close()
                    os.write(1, "\r-> RESULT %s %s\n\r" % (endpoint, response_body))
                    sys.stdout.flush()
                    if response_body == "ok":
                        ips.pop(i)
                        os.write(1, "\r-> REMAIN %s\n\r" % str(ips))

                except urllib2.URLError:
                    os.write(2, "\r-> NOT READY %s\n\r" % ip)
                    time.sleep(10)
        self.assertEqual(len(ips), 0)

    @staticmethod
    def host_total_memory_mib():
        mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
        mem_gib = mem_bytes / (1024. ** 3)
        return mem_gib * 1024
