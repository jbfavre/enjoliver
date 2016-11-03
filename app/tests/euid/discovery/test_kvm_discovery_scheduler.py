import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib2
from multiprocessing import Process
from unittest import TestCase

from app import api
from app import generator
from app import scheduler


@unittest.skipIf(os.geteuid() != 0,
                 "TestKVMDiscovery need privilege")
class TestKVMDiscoveryScheduler(TestCase):
    p_bootcfg = Process
    p_dnsmasq = Process
    p_api = Process
    gen = generator.Generator

    basic_path = "%s" % os.path.dirname(os.path.abspath(__file__))
    euid_path = "%s" % os.path.dirname(basic_path)
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

    api_host = "172.15.0.1"
    api_endpoint = "http://%s:%d" % (api_host, api_port)

    dev_null = None

    @staticmethod
    def process_target_bootcfg():
        cmd = [
            "%s/bootcfg_dir/bootcfg" % TestKVMDiscoveryScheduler.tests_path,
            "-data-path", "%s" % TestKVMDiscoveryScheduler.test_bootcfg_path,
            "-assets-path", "%s" % TestKVMDiscoveryScheduler.assets_path,
            "-address", "%s" % TestKVMDiscoveryScheduler.bootcfg_address,
            "-log-level", "debug"
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execv(cmd[0], cmd)

    @staticmethod
    def process_target_api():
        api.cache.clear()
        api.app.run(host=TestKVMDiscoveryScheduler.api_host, port=TestKVMDiscoveryScheduler.api_port)

    @staticmethod
    def process_target_dnsmasq():
        cmd = [
            "%s/rkt_dir/rkt" % TestKVMDiscoveryScheduler.tests_path,
            # "--debug",
            "--dir=%s/rkt_dir/data" % TestKVMDiscoveryScheduler.tests_path,
            "--local-config=%s" % TestKVMDiscoveryScheduler.tests_path,
            "--mount",
            "volume=config,target=/etc/dnsmasq.conf",
            "run",
            "quay.io/coreos/dnsmasq:v0.3.0",
            "--insecure-options=all",
            "--net=host",
            "--interactive",
            "--uuid-file-save=/tmp/dnsmasq.uuid",
            "--volume",
            "config,kind=host,source=%s/dnsmasq-metal0.conf" % TestKVMDiscoveryScheduler.tests_path
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execv(cmd[0], cmd)
        os._exit(2)

    @staticmethod
    def process_target_create_metal0():
        cmd = [
            "%s/rkt_dir/rkt" % TestKVMDiscoveryScheduler.tests_path,
            # "--debug",
            "--dir=%s/rkt_dir/data" % TestKVMDiscoveryScheduler.tests_path,
            "--local-config=%s" % TestKVMDiscoveryScheduler.tests_path,
            "run",
            "quay.io/coreos/dnsmasq:v0.3.0",
            "--insecure-options=all",
            "--net=metal0",
            "--interactive",
            "--exec",
            "/bin/true"]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execv(cmd[0], cmd)
        os._exit(2)  # Should not happen

    @staticmethod
    def dns_masq_running():
        """
        net.d/10-metal0.conf
        {
            "name": "metal0",
            "type": "bridge",
            "bridge": "metal0",
            "isGateway": true,
            "ipMasq": true,
            "ipam": {
                "type": "host-local",
                "subnet": "172.15.0.0/16",
                "routes" : [ { "dst" : "0.0.0.0/0" } ]
            }
        }
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = 1
        for i in xrange(120):
            result = sock.connect_ex(('172.15.0.1', 53))
            if result == 0:
                break
            time.sleep(0.5)
            if i % 10 == 0:
                os.write(1, "DNSMASQ still NOT ready\n\r")
        assert result == 0
        os.write(1, "DNSMASQ ready\n\r")
        sys.stdout.flush()

    @classmethod
    def generator(cls):
        marker = "%s" % cls.__name__.lower()
        ignition_file = "sudo-%s.yaml" % marker

        cls.gen = generator.Generator(
            profile_id="id-%s" % marker,
            name="name-%s" % marker,
            ignition_id=ignition_file,
            bootcfg_path=cls.test_bootcfg_path)

        cls.gen.dumps()

    @classmethod
    def setUpClass(cls):
        if os.geteuid() != 0:
            raise RuntimeError("Need to be root EUID==%d" % os.geteuid())

        cls.clean_sandbox()

        if os.path.isfile("%s/rkt_dir/rkt" % TestKVMDiscoveryScheduler.tests_path) is False or \
                        os.path.isfile("%s/bootcfg_dir/bootcfg" % TestKVMDiscoveryScheduler.tests_path) is False:
            os.write(2, "Call 'make' as user for:\n"
                        "- %s/rkt_dir/rkt\n" % TestKVMDiscoveryScheduler.tests_path +
                     "- %s/bootcfg_dir/bootcfg\n" % TestKVMDiscoveryScheduler.tests_path)
            exit(2)

        os.write(1, "PPID -> %s\n" % os.getpid())
        cls.p_bootcfg = Process(target=TestKVMDiscoveryScheduler.process_target_bootcfg)
        cls.p_bootcfg.start()
        assert cls.p_bootcfg.is_alive() is True

        if subprocess.call(["ip", "link", "show", "metal0"], stdout=None) != 0:
            p_create_metal0 = Process(
                target=TestKVMDiscoveryScheduler.process_target_create_metal0)
            p_create_metal0.start()
            for i in xrange(60):
                if p_create_metal0.exitcode == 0:
                    os.write(1, "Bridge done\n\r")
                    break
                os.write(1, "Bridge not ready\n\r")
                time.sleep(0.5)
        assert subprocess.call(["ip", "link", "show", "metal0"]) == 0

        cls.p_dnsmasq = Process(target=TestKVMDiscoveryScheduler.process_target_dnsmasq)
        cls.p_dnsmasq.start()
        assert cls.p_dnsmasq.is_alive() is True
        TestKVMDiscoveryScheduler.dns_masq_running()

        cls.p_api = Process(target=TestKVMDiscoveryScheduler.process_target_api)
        cls.p_api.start()
        assert cls.p_api.is_alive() is True

        cls.dev_null = open("/dev/null", "w")

    @classmethod
    def tearDownClass(cls):
        os.write(1, "\n\rTERM -> %d\n\r" % cls.p_bootcfg.pid)
        sys.stdout.flush()
        cls.p_bootcfg.terminate()
        cls.p_bootcfg.join(timeout=5)
        cls.p_dnsmasq.terminate()
        cls.p_dnsmasq.join(timeout=5)
        cls.p_api.terminate()
        cls.p_api.join(timeout=5)
        # cls.clean_sandbox()
        subprocess.call([
            "%s/rkt_dir/rkt" % TestKVMDiscoveryScheduler.tests_path,
            "--debug",
            "--dir=%s/rkt_dir/data" % TestKVMDiscoveryScheduler.tests_path,
            "--local-config=%s" % TestKVMDiscoveryScheduler.tests_path,
            "gc",
            "--grace-period=0s"])
        cls.dev_null.close()

    @staticmethod
    def clean_sandbox():
        dirs = ["%s/%s" % (TestKVMDiscoveryScheduler.test_bootcfg_path, k)
                for k in ("profiles", "groups")]
        for d in dirs:
            for f in os.listdir(d):
                if ".json" in f:
                    os.write(1, "\r-> remove %s\n\r" % f)
                    os.remove("%s/%s" % (d, f))

    def setUp(self):
        self.assertTrue(self.p_bootcfg.is_alive())
        self.assertTrue(self.p_dnsmasq.is_alive())
        self.assertTrue(self.p_api.is_alive())

        self.clean_sandbox()
        for i in xrange(10):
            try:
                self.assertIsNone(self.fetch_discovery_interfaces()["interfaces"])
            except urllib2.URLError:
                time.sleep(0.5)

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


@unittest.skipIf(os.geteuid() != 0,
                 "TestKVMDiscovery need privilege")
class TestKVMDiscoveryScheduler0(TestKVMDiscoveryScheduler):
    # @unittest.skip("just skip")
    def test_00(self):
        self.assertIsNone(self.fetch_discovery_interfaces()["interfaces"])
        nb_node = 3
        marker = "euid-%s-%s" % (TestKVMDiscoveryScheduler.__name__.lower(), self.test_00.__name__)
        os.environ["BOOTCFG_IP"] = "172.15.0.1"
        gen = generator.Generator(
            profile_id="%s" % marker,
            name="%s" % marker,
            ignition_id="%s.yaml" % marker,
            bootcfg_path=self.test_bootcfg_path
        )
        gen.dumps()

        try:
            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                destroy, undefine = ["virsh", "destroy", "%s" % machine_marker], \
                                    ["virsh", "undefine", "%s" % machine_marker]
                self.virsh(destroy, v=self.dev_null), self.virsh(undefine, v=self.dev_null)
                virt_install = [
                    "virt-install",
                    "--name",
                    "%s" % machine_marker,
                    "--network=bridge:metal0,model=virtio",
                    "--memory=1024",
                    "--vcpus=1",
                    "--pxe",
                    "--disk",
                    "none",
                    "--os-type=linux",
                    "--os-variant=generic",
                    "--noautoconsole",
                    "--boot=network"
                ]
                self.virsh(virt_install, assertion=True, v=self.dev_null)
                time.sleep(3)  # KVM fail to associate nic

            sch = scheduler.EtcdScheduler(
                api_endpoint=self.api_endpoint,
                bootcfg_path=self.test_bootcfg_path,
                ignition_member="%s-emember" % marker,
                ignition_proxy="%s-eproxy" % marker,
                bootcfg_prefix="%s-" % marker
            )
            sch.etcd_members_nb = 1

            for i in xrange(30):
                if sch.apply() is True:
                    break
                time.sleep(2)

            interfaces = self.fetch_discovery_interfaces()

            # time.sleep(600)

            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                reset = ["virsh", "reset", "%s" % machine_marker]
                self.virsh(reset), os.write(1, "\r")

            time.sleep(1)

            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                start = ["virsh", "start", "%s" % machine_marker]
                self.virsh(start), os.write(1, "\r")
                time.sleep(3)

            ips_collected = []

            for machine in interfaces["interfaces"]:
                for i in machine:
                    if i["name"] == "eth0":
                        ips_collected.append(i["IPv4"])

            os.write(2, "\rIPs collected: %s\n\r" % ips_collected)

            one_etcd = False
            for i in xrange(30):
                for ip in ips_collected:
                    try:
                        endpoint = "http://%s:2379/health" % ip
                        request = urllib2.urlopen(endpoint)
                        response_body = json.loads(request.read())
                        request.close()
                        if response_body == {u'health': u'true'}:
                            # one_etcd = Just One
                            self.assertFalse(one_etcd)
                            one_etcd = True
                            os.write(2, "\r%s %s\n\r" % (endpoint, response_body))
                            break

                    except urllib2.URLError:
                        pass

                if one_etcd is True:
                    break

                time.sleep(2)

            self.assertTrue(one_etcd)

        finally:
            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                destroy, undefine = ["virsh", "destroy", "%s" % machine_marker], \
                                    ["virsh", "undefine", "%s" % machine_marker]
                self.virsh(destroy), os.write(1, "\r")
                self.virsh(undefine), os.write(1, "\r")


@unittest.skipIf(os.geteuid() != 0,
                 "TestKVMDiscovery need privilege")
class TestKVMDiscoveryScheduler2(TestKVMDiscoveryScheduler):
    # @unittest.skip("just skip")
    def test_01(self):
        self.assertIsNone(self.fetch_discovery_interfaces()["interfaces"])
        nb_node = 3
        marker = "euid-%s-%s" % (TestKVMDiscoveryScheduler.__name__.lower(), self.test_01.__name__)
        os.environ["BOOTCFG_IP"] = "172.15.0.1"
        gen = generator.Generator(
            profile_id="%s" % marker,
            name="%s" % marker,
            ignition_id="%s.yaml" % marker,
            bootcfg_path=self.test_bootcfg_path
        )
        gen.dumps()

        try:
            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                destroy, undefine = ["virsh", "destroy", "%s" % machine_marker], \
                                    ["virsh", "undefine", "%s" % machine_marker]
                self.virsh(destroy, v=self.dev_null), self.virsh(undefine, v=self.dev_null)
                virt_install = [
                    "virt-install",
                    "--name",
                    "%s" % machine_marker,
                    "--network=bridge:metal0,model=virtio",
                    "--memory=1024",
                    "--vcpus=1",
                    "--pxe",
                    "--disk",
                    "none",
                    "--os-type=linux",
                    "--os-variant=generic",
                    "--noautoconsole",
                    "--boot=network"
                ]
                self.virsh(virt_install, assertion=True, v=self.dev_null)
                time.sleep(3)  # KVM fail to associate nic

            sch = scheduler.EtcdScheduler(
                api_endpoint=self.api_endpoint,
                bootcfg_path=self.test_bootcfg_path,
                ignition_member="%s-emember" % marker,
                ignition_proxy="%s-eproxy" % marker,
                bootcfg_prefix="%s-" % marker
            )
            # sch.etcd_members_nb = 3 # This is by default

            for i in xrange(30):
                if sch.apply() is True:
                    break
                time.sleep(2)

            os.write(2, "\r")
            interfaces = self.fetch_discovery_interfaces()

            # time.sleep(600)
            os.write(2, "\r-> start reboot nodes\n\r")

            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                reset = ["virsh", "reset", "%s" % machine_marker]
                self.virsh(reset), os.write(1, "\r")

            time.sleep(1)

            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                start = ["virsh", "start", "%s" % machine_marker]
                self.virsh(start), os.write(1, "\r")
                time.sleep(3)

            os.write(2, "\r-> start reboot asked\n\r")

            ips_collected = []

            for machine in interfaces["interfaces"]:
                for i in machine:
                    if i["name"] == "eth0":
                        ips_collected.append(i["IPv4"])

            os.write(2, "\rIPs collected: %s\n\r" % ips_collected)

            etcd = 0
            for i in xrange(30):
                for ip in ips_collected:
                    try:
                        endpoint = "http://%s:2379/health" % ip
                        request = urllib2.urlopen(endpoint)
                        response_body = json.loads(request.read())
                        request.close()
                        if response_body == {u'health': u'true'}:
                            etcd += 1
                            os.write(2, "\r%s %s\n\r" % (endpoint, response_body))

                    except urllib2.URLError:
                        pass

                if etcd == nb_node:
                    break

                time.sleep(2)

            self.assertTrue(etcd)

        finally:
            for i in xrange(nb_node):
                machine_marker = "%s-%d" % (marker, i)
                destroy, undefine = ["virsh", "destroy", "%s" % machine_marker], \
                                    ["virsh", "undefine", "%s" % machine_marker]
                self.virsh(destroy), os.write(1, "\r")
                self.virsh(undefine), os.write(1, "\r")


if __name__ == "__main__":
    unittest.main()
