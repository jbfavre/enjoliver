#! /usr/bin/env python
import os
import sys

import time

try:
    import generator
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import generator

import scheduler


class Enjolivage(object):
    wait = 10

    def __init__(self, marker, bootcfg_path="/var/lib/bootcfg", api_uri="http://127.0.0.1:8000"):
        self.api_uri = api_uri
        self.marker = marker
        self.bootcfg_path = bootcfg_path

        self._init_discovery()

        self._k8s_control_plane = scheduler.EtcdMemberK8sControlPlaneScheduler(
            api_endpoint=self.api_uri,
            bootcfg_path=self.bootcfg_path,
            ignition_member="%s-etcd-member-control-plane" % self.marker,
            bootcfg_prefix="%s-" % self.marker
        )
        self._k8s_node = scheduler.K8sNodeScheduler(
            k8s_control_plane=self.etcd_member_k8s_control_plane,
            ignition_node="%s-k8s-node" % self.marker,
            apply_first=False
        )

    def _init_discovery(self):
        gen = generator.Generator(
            profile_id="%s" % self.marker,
            name="%s" % self.marker,
            ignition_id="%s.yaml" % self.marker,
            bootcfg_path=self.bootcfg_path
        )
        gen.dumps()

    @property
    def etcd_member_k8s_control_plane(self):
        return self._k8s_control_plane

    @property
    def k8s_node(self):
        return self._k8s_node

    def run(self):
        while self._k8s_control_plane.apply() is False:
            time.sleep(self.wait)
        return self._k8s_node.apply()