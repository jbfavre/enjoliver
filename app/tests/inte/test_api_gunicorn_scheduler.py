import httplib
import json
import os
import shutil
import sys
import time
import unittest
import urllib2
from multiprocessing import Process

import requests

from app import api
from app import model
from app import schedulerv2
from app import sync_matchbox
from common import posts


class TestAPIGunicornScheduler(unittest.TestCase):
    p_matchbox = Process
    p_api = Process

    inte_path = "%s" % os.path.dirname(__file__)
    dbs_path = "%s/dbs" % inte_path
    tests_path = "%s" % os.path.dirname(inte_path)
    app_path = os.path.dirname(tests_path)
    project_path = os.path.dirname(app_path)
    matchbox_path = "%s/matchbox" % project_path
    assets_path = "%s/matchbox/assets" % project_path

    runtime_path = "%s/runtime" % project_path
    rkt_bin = "%s/rkt/rkt" % runtime_path
    matchbox_bin = "%s/matchbox/matchbox" % runtime_path

    test_matchbox_path = "%s/test_matchbox" % tests_path

    matchbox_port = int(os.getenv("MATCHBOX_PORT", "8080"))

    matchbox_uri = "http://localhost:%d" % matchbox_port

    api_port = int(os.getenv("API_PORT", "5000"))

    api_address = "0.0.0.0:%d" % api_port
    api_uri = "http://localhost:%d" % api_port

    api_discovery = "%s/discovery" % api_uri

    @staticmethod
    def process_target_matchbox():
        cmd = [
            "%s" % TestAPIGunicornScheduler.matchbox_bin,
            "-data-path", "%s" % TestAPIGunicornScheduler.test_matchbox_path,
            "-assets-path", "%s" % TestAPIGunicornScheduler.assets_path,
            "-log-level", "debug"
        ]
        os.write(1, "PID  -> %s\n"
                    "exec -> %s\n" % (
                     os.getpid(), " ".join(cmd)))
        sys.stdout.flush()
        os.execv(cmd[0], cmd)

    @staticmethod
    def clean_sandbox():
        dirs = ["%s/%s" % (TestAPIGunicornScheduler.test_matchbox_path, k)
                for k in ("profiles", "groups")]
        for d in dirs:
            for f in os.listdir(d):
                if ".json" in f:
                    os.write(1, "\r-> remove %s\n\r" % f)
                    os.remove("%s/%s" % (d, f))

    @staticmethod
    def process_target_api():
        api.cache.clear()
        os.environ["API_URI"] = "http://localhost:5000"
        os.environ["DB_PATH"] = "%s/%s.sqlite" % (
            TestAPIGunicornScheduler.dbs_path, TestAPIGunicornScheduler.__name__.lower())
        os.environ["IGNITION_JOURNAL_DIR"] = "%s/ignition_journal" % TestAPIGunicornScheduler.inte_path
        cmd = [
            "%s/manage.py" % TestAPIGunicornScheduler.project_path,
            "gunicorn"
        ]
        os.execve(cmd[0], cmd, os.environ)

    @classmethod
    def setUpClass(cls):
        time.sleep(0.1)
        db_path = "%s/%s.sqlite" % (cls.dbs_path, TestAPIGunicornScheduler.__name__.lower())
        db = "sqlite:///%s" % db_path
        journal = "%s/ignition_journal" % cls.inte_path
        try:
            os.remove(db_path)
        except OSError:
            pass

        try:
            shutil.rmtree(journal)
        except OSError:
            pass

        assert os.path.isdir(journal) is False

        cls.clean_sandbox()

        engine = api.create_engine(db)
        api.app.config["DB_PATH"] = db_path
        api.app.config["API_URI"] = cls.api_uri
        model.Base.metadata.create_all(engine)
        assert os.path.isfile(db_path)
        api.engine = engine

        if os.path.isfile("%s" % TestAPIGunicornScheduler.matchbox_bin) is False:
            raise IOError("%s" % TestAPIGunicornScheduler.matchbox_bin)
        cls.p_matchbox = Process(target=TestAPIGunicornScheduler.process_target_matchbox)
        cls.p_api = Process(target=TestAPIGunicornScheduler.process_target_api)
        os.write(1, "PPID -> %s\n" % os.getpid())
        cls.p_matchbox.start()
        assert cls.p_matchbox.is_alive() is True
        cls.p_api.start()
        assert cls.p_api.is_alive() is True

        cls.matchbox_running(cls.matchbox_uri, cls.p_matchbox)
        cls.api_running(cls.api_uri, cls.p_api)

    @classmethod
    def tearDownClass(cls):
        os.write(1, "TERM -> %d\n" % cls.p_matchbox.pid)
        sys.stdout.flush()
        cls.p_matchbox.terminate()
        cls.p_matchbox.join(timeout=5)
        cls.p_api.terminate()
        cls.p_api.join(timeout=5)
        time.sleep(0.1)

    @staticmethod
    def matchbox_running(matchbox_endpoint, p_matchbox):
        response_body = ""
        response_code = 404
        for i in xrange(100):
            assert p_matchbox.is_alive() is True
            try:
                request = urllib2.urlopen(matchbox_endpoint)
                response_body = request.read()
                response_code = request.code
                request.close()
                break

            except httplib.BadStatusLine:
                time.sleep(0.5)

            except urllib2.URLError:
                time.sleep(0.5)

        assert "matchbox\n" == response_body
        assert 200 == response_code

    @staticmethod
    def api_running(api_endpoint, p_api):
        response_code = 404
        for i in xrange(100):
            assert p_api.is_alive() is True
            try:
                request = urllib2.urlopen(api_endpoint)
                response_code = request.code
                request.close()
                break

            except httplib.BadStatusLine:
                time.sleep(0.5)

            except urllib2.URLError:
                time.sleep(0.5)

        assert 200 == response_code

    def setUp(self):
        self.assertTrue(self.p_matchbox.is_alive())
        self.assertTrue(self.p_api.is_alive())
        self.api_healthz()

    def api_healthz(self):
        expect = {
            u'flask': True,
            u'global': True,
            u'db': True,
            u'matchbox': {
                u'/': True,
                u'/boot.ipxe': True,
                u'/boot.ipxe.0': True,
                u'/assets': True,
                u"/metadata": True
            }}
        request = urllib2.urlopen("%s/healthz" % self.api_uri)
        response_body = request.read()
        response_code = request.code
        request.close()
        self.assertEqual(json.loads(response_body), expect)
        self.assertEqual(200, response_code)


# @unittest.skip("skip")
class TestEtcdMemberKubernetesControlPlane1(TestAPIGunicornScheduler):
    def test_01(self):
        r = requests.post(self.api_discovery, data=json.dumps(posts.M01))
        self.assertEqual(r.status_code, 200)
        sch = schedulerv2.EtcdMemberKubernetesControlPlane(self.api_uri)
        sch.expected_nb = 1
        self.assertTrue(sch.apply())
        self.assertTrue(sch.apply())


class TestEtcdMemberKubernetesControlPlane2(TestAPIGunicornScheduler):
    def test_02(self):
        r = requests.post(self.api_discovery, data=json.dumps(posts.M01))
        r.close()
        self.assertEqual(r.status_code, 200)
        sch = schedulerv2.EtcdMemberKubernetesControlPlane(self.api_uri)
        self.assertFalse(sch.apply())
        self.assertFalse(sch.apply())
        r = requests.post(self.api_discovery, data=json.dumps(posts.M02))
        r.close()
        self.assertFalse(sch.apply())
        r = requests.post(self.api_discovery, data=json.dumps(posts.M03))
        r.close()
        self.assertTrue(sch.apply())

        s = sync_matchbox.ConfigSyncSchedules(
            self.api_uri,
            self.test_matchbox_path,
            ignition_dict={
                "etcd_member_kubernetes_control_plane": "inte-testapigunicornscheduler-etcd-k8s-cp",
                "kubernetes_nodes": "inte-testapigunicornscheduler-etcd-k8s-cp",
            }
        )
        s.apply()


class TestEtcdMemberKubernetesControlPlane3(TestAPIGunicornScheduler):
    def test_03(self):
        r = requests.post(self.api_discovery, data=json.dumps(posts.M01))
        r.close()
        self.assertEqual(r.status_code, 200)
        sch = schedulerv2.EtcdMemberKubernetesControlPlane(self.api_uri)
        self.assertFalse(sch.apply())
        self.assertFalse(sch.apply())
        r = requests.post(self.api_discovery, data=json.dumps(posts.M02))
        r.close()
        self.assertFalse(sch.apply())
        r = requests.post(self.api_discovery, data=json.dumps(posts.M03))
        r.close()
        self.assertTrue(sch.apply())

        sch_no = schedulerv2.KubernetesNode(self.api_uri, True)
        self.assertEqual(0, sch_no.apply())
        r = requests.post(self.api_discovery, data=json.dumps(posts.M04))
        r.close()
        self.assertEqual(1, sch_no.apply())

        s = sync_matchbox.ConfigSyncSchedules(
            self.api_uri,
            self.test_matchbox_path,
            ignition_dict={
                "etcd_member_kubernetes_control_plane": "inte-testapigunicornscheduler-etcd-k8s-cp",
                "kubernetes_nodes": "inte-testapigunicornscheduler-etcd-k8s-cp",
            },
        )
        s.apply()


class TestEtcdMemberKubernetesControlPlane4(TestAPIGunicornScheduler):
    def test_04(self):
        for p in posts.ALL:
            r = requests.post(self.api_discovery, data=json.dumps(p))
            self.assertEqual(r.status_code, 200)
            r.close()

        sch_no = schedulerv2.KubernetesNode(self.api_uri, True)

        self.assertEqual(len(posts.ALL) - schedulerv2.EtcdMemberKubernetesControlPlane.expected_nb, sch_no.apply())

        s = sync_matchbox.ConfigSyncSchedules(
            self.api_uri,
            self.test_matchbox_path,
            ignition_dict={
                "etcd_member_kubernetes_control_plane": "inte-testapigunicornscheduler-etcd-k8s-cp",
                "kubernetes_nodes": "inte-testapigunicornscheduler-etcd-k8s-cp",
            },
            extra_selector_dict={"os": "installed"},
        )
        s.apply()
