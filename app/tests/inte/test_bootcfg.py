import httplib
import json
import os
import urllib2
from unittest import TestCase
from multiprocessing import Process
import subprocess

import time

from app import generator


class TestBootConfigCommon(TestCase):
    p_bootcfg = Process
    gen = generator.Generator

    func_path = "%s" % os.path.dirname(__file__)
    tests_path = "%s" % os.path.split(func_path)[0]
    app_path = os.path.split(tests_path)[0]
    project_path = os.path.split(app_path)[0]
    bootcfg_path = "%s/bootcfg" % project_path
    assets_path = "%s/bootcfg/assets" % project_path

    test_bootcfg_path = "%s/test_bootcfg" % tests_path

    bootcfg_address = "0.0.0.0:8080"
    bootcfg_endpoint = "http://localhost:8080"

    @staticmethod
    def process_target():
        cmd = [
            "%s/bin/bootcfg" % TestBootConfigCommon.tests_path,
            "-data-path", "%s" % TestBootConfigCommon.test_bootcfg_path,
            "-assets-path", "%s" % TestBootConfigCommon.assets_path,
            "-address", "%s" % TestBootConfigCommon.bootcfg_address
        ]
        print " ".join(cmd)
        os.execv(cmd[0], cmd)

    @classmethod
    def generator(cls):
        marker = "%s" % cls.__name__.lower()
        ignition_file = "inte-%s.yaml" % marker
        cls.gen = generator.Generator(_id="id-%s" % marker,
                                      name="name-%s" % marker,
                                      ignition_id=ignition_file,
                                      bootcfg_path=cls.test_bootcfg_path)
        cls.gen.dumps()

    @classmethod
    def setUpClass(cls):

        cls.clean_sandbox()

        subprocess.check_output(["make"], cwd=cls.project_path)
        cls.p_bootcfg = Process(target=TestBootConfigHelloWorld.process_target)
        cls.p_bootcfg.start()
        assert cls.p_bootcfg.is_alive() is True

        cls.generator()

    @classmethod
    def tearDownClass(cls):
        print "\nSIGTERM -> %d" % cls.p_bootcfg.pid
        cls.p_bootcfg.terminate()
        cls.p_bootcfg.join(timeout=5)
        cls.clean_sandbox()

    @staticmethod
    def clean_sandbox():
        dirs = ["%s/%s" % (TestBootConfigCommon.test_bootcfg_path, k) for k in ("profiles", "groups")]
        for d in dirs:
            for f in os.listdir(d):
                if ".json" in f:
                    os.remove("%s/%s" % (d, f))

    def setUp(self):
        self.assertTrue(self.p_bootcfg.is_alive())
        try:
            self.assertEqual(self.gen.group.ip_address, self.gen.profile.ip_address)
        except AttributeError:
            # gen not declared
            pass

    def test_00_running(self):
        response_body = ""
        response_code = 404
        for i in xrange(100):
            try:
                request = urllib2.urlopen(self.bootcfg_endpoint)
                response_body = request.read()
                response_code = request.code
                request.close()
                break

            except httplib.BadStatusLine:
                time.sleep(0.01)

            except urllib2.URLError:
                time.sleep(0.01)

        self.assertEqual("bootcfg\n", response_body)
        self.assertEqual(200, response_code)

    def test_01_boot_dot_ipxe(self):
        request = urllib2.urlopen("%s/boot.ipxe" % self.bootcfg_endpoint)
        response = request.read()
        request.close()
        self.assertEqual(
            response,
            "#!ipxe\n"
            "chain "
            "ipxe?uuid=${uuid}"
            "&mac=${net0/mac:hexhyp}"
            "&domain=${domain}"
            "&hostname=${hostname}"
            "&serial=${serial}\n")

    def test_02_ipxe(self):
        request = urllib2.urlopen("%s/ipxe" % self.bootcfg_endpoint)
        response = request.read()
        request.close()

        response = response.replace(" \n", "\n")
        lines = response.split("\n")
        lines = [k for k in lines if k]

        shebang = lines[0]
        self.assertEqual(shebang, "#!ipxe")

        kernel = lines[1].split(" ")
        kernel_expect = [
            'kernel',
            '/assets/coreos/serve/coreos_production_pxe.vmlinuz',
            'coreos.autologin',
            'coreos.config.url=http://%s:8080/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp}' % self.gen.group.ip_address,
            'coreos.first_boot']
        self.assertEqual(kernel, kernel_expect)

        init_rd = lines[2].split(" ")
        init_rd_expect = ['initrd', '/assets/coreos/serve/coreos_production_pxe_image.cpio.gz']
        self.assertEqual(init_rd, init_rd_expect)

        boot = lines[3]
        self.assertEqual(boot, "boot")
        self.assertEqual(len(lines), 4)

    def test_03_assets(self):
        request = urllib2.urlopen("%s/assets" % self.bootcfg_endpoint)
        request.close()
        self.assertEqual(200, request.code)

    def test_03_assets_coreos(self):
        request = urllib2.urlopen("%s/assets/coreos" % self.bootcfg_endpoint)
        request.close()
        self.assertEqual(200, request.code)

    def test_03_assets_coreos_serve(self):
        request = urllib2.urlopen("%s/assets/coreos/serve" % self.bootcfg_endpoint)
        request.close()
        self.assertEqual(200, request.code)

    def test_03_assets_coreos_serve_kernel(self):
        request = urllib2.urlopen("%s/assets/coreos/serve/coreos_production_pxe.vmlinuz" % self.bootcfg_endpoint)
        request.close()
        self.assertEqual(200, request.code)

    def test_03_assets_coreos_serve_initrd(self):
        request = urllib2.urlopen("%s/assets/coreos/serve/coreos_production_pxe_image.cpio.gz" % self.bootcfg_endpoint)
        request.close()
        self.assertEqual(200, request.code)

    def test_03_assets_coreos_serve_404(self):
        with self.assertRaises(urllib2.HTTPError):
            urllib2.urlopen("%s/assets/coreos/serve/404_request.not-here" % self.bootcfg_endpoint)


class TestBootConfigHelloWorld(TestBootConfigCommon):
    def test_a0_ignition(self):
        request = urllib2.urlopen("%s/ignition" % self.bootcfg_endpoint)
        response = request.read()
        request.close()

        ign_resp = json.loads(response)
        expect = {
            u'networkd': {},
            u'passwd': {},
            u'systemd': {},
            u'storage': {
                u'files': [{
                    u'group': {},
                    u'user': {},
                    u'filesystem':
                        u'root',
                    u'path': u'/tmp/hello',
                    u'contents': {
                        u'source': u'data:,Hello%20World%0A',
                        u'verification': {}
                    },
                    u'mode': 420}
                ]
            },
            u'ignition': {u'version': u'2.0.0', u'config': {}}}
        self.assertEqual(ign_resp, expect)


class TestBootConfigSelector(TestBootConfigCommon):
    mac = "00:00:00:00:00:00"

    @classmethod
    def generator(cls):
        marker = "%s" % cls.__name__.lower()
        ignition_file = "inte-%s.yaml" % marker
        cls.gen = generator.Generator(_id="id-%s" % marker,
                                      name="name-%s" % marker,
                                      ignition_id=ignition_file,
                                      selector={"mac": cls.mac},
                                      bootcfg_path=cls.test_bootcfg_path)
        cls.gen.dumps()

    def test_02_ipxe(self):
        request = urllib2.urlopen("%s/ipxe?mac=%s" % (self.bootcfg_endpoint, self.mac))
        response = request.read()
        request.close()

        response = response.replace(" \n", "\n")
        lines = response.split("\n")
        lines = [k for k in lines if k]

        shebang = lines[0]
        self.assertEqual(shebang, "#!ipxe")

        kernel = lines[1].split(" ")
        kernel_expect = [
            'kernel',
            '/assets/coreos/serve/coreos_production_pxe.vmlinuz',
            'coreos.autologin',
            'coreos.config.url=http://%s:8080/ignition?uuid=${uuid}&mac=${net0/mac:hexhyp}' % self.gen.group.ip_address,
            'coreos.first_boot']
        self.assertEqual(kernel, kernel_expect)

        init_rd = lines[2].split(" ")
        init_rd_expect = ['initrd', '/assets/coreos/serve/coreos_production_pxe_image.cpio.gz']
        self.assertEqual(init_rd, init_rd_expect)

        boot = lines[3]
        self.assertEqual(boot, "boot")
        self.assertEqual(len(lines), 4)

    def test_a1_ipxe_raise(self):
        with self.assertRaises(urllib2.HTTPError):
            urllib2.urlopen("%s/ipxe" % self.bootcfg_endpoint)

    def test_a2_ipxe_raise(self):
        with self.assertRaises(urllib2.HTTPError):
            urllib2.urlopen("%s/ignition?mac=%s" % (self.bootcfg_endpoint, "01:01:01:01:01"))

    def test_a0_ignition(self):
        request = urllib2.urlopen("%s/ignition?mac=%s" % (self.bootcfg_endpoint, self.mac))
        response = request.read()
        request.close()

        ign_resp = json.loads(response)
        expect = {
            u'networkd': {},
            u'passwd': {},
            u'systemd': {},
            u'storage': {
                u'files': [
                    {
                        u'group': {},
                        u'user': {},
                        u'filesystem': u'root',
                        u'path': u'/tmp/selector',
                        u'contents': {
                            u'source': u'data:,BySelector%0A', u'verification': {}
                        },
                        u'mode': 420}]
            },
            u'ignition': {u'version': u'2.0.0', u'config': {}}}
        self.assertEqual(ign_resp, expect)


class TestBootConfigSelectors(TestBootConfigCommon):
    mac_one = "00:00:00:00:00:01"
    mac_two = "00:00:00:00:00:02"
    mac_three = "00:00:00:00:00:03"

    # @staticmethod
    # def clean_sandbox():
    #     # Don't clean
    #     pass

    @classmethod
    def generator(cls):
        marker_one = "%s-one" % cls.__name__.lower()
        ignition_file = "inte-%s.yaml" % marker_one
        gen_one = generator.Generator(_id="id-%s" % marker_one,
                                      name="name-%s" % marker_one,
                                      ignition_id=ignition_file,
                                      selector={"mac": cls.mac_one},
                                      bootcfg_path=cls.test_bootcfg_path)
        gen_one.dumps()

        marker_two = "%s-two" % cls.__name__.lower()
        ignition_file = "inte-%s.yaml" % marker_two
        gen_one = generator.Generator(_id="id-%s" % marker_two,
                                      name="name-%s" % marker_two,
                                      ignition_id=ignition_file,
                                      selector={"mac": cls.mac_two},
                                      bootcfg_path=cls.test_bootcfg_path)
        gen_one.dumps()

        marker_three = "%s-three" % cls.__name__.lower()
        ignition_file = "inte-testbootconfigselectors-default.yaml"
        gen_one = generator.Generator(_id="id-%s" % marker_three,
                                      name="name-%s" % marker_three,
                                      ignition_id=ignition_file,
                                      bootcfg_path=cls.test_bootcfg_path)
        gen_one.dumps()

    def test_ignition_1(self):
        request = urllib2.urlopen("%s/ignition?mac=%s" % (self.bootcfg_endpoint, self.mac_one))
        response = request.read()
        request.close()

        ign_resp = json.loads(response)
        expect = {
            u'networkd': {},
            u'passwd': {},
            u'systemd': {},
            u'storage': {
                u'files': [
                    {
                        u'group': {},
                        u'user': {},
                        u'filesystem': u'root',
                        u'path': u'/tmp/selector',
                        u'contents': {
                            u'source': u'data:,BySelectorOne%0A', u'verification': {}
                        },
                        u'mode': 420}]
            },
            u'ignition': {u'version': u'2.0.0', u'config': {}}}
        self.assertEqual(ign_resp, expect)

    def test_ignition_2(self):
        request = urllib2.urlopen("%s/ignition?mac=%s" % (self.bootcfg_endpoint, self.mac_two))
        response = request.read()
        request.close()

        ign_resp = json.loads(response)
        expect = {
            u'networkd': {},
            u'passwd': {},
            u'systemd': {},
            u'storage': {
                u'files': [
                    {
                        u'group': {},
                        u'user': {},
                        u'filesystem': u'root',
                        u'path': u'/tmp/selector',
                        u'contents': {
                            u'source': u'data:,BySelectorTwo%0A', u'verification': {}
                        },
                        u'mode': 420}]
            },
            u'ignition': {u'version': u'2.0.0', u'config': {}}}
        self.assertEqual(ign_resp, expect)

    def test_ignition_3(self):
        request = urllib2.urlopen("%s/ignition?mac=%s" % (self.bootcfg_endpoint, self.mac_three))
        response = request.read()
        request.close()

        ign_resp = json.loads(response)
        expect = {
            u'networkd': {},
            u'passwd': {},
            u'systemd': {},
            u'storage': {
                u'files': [
                    {
                        u'group': {},
                        u'user': {},
                        u'filesystem': u'root',
                        u'path': u'/tmp/selector',
                        u'contents': {
                            u'source': u'data:,NoSelector%0A', u'verification': {}
                        },
                        u'mode': 420}]
            },
            u'ignition': {u'version': u'2.0.0', u'config': {}}}
        self.assertEqual(ign_resp, expect)