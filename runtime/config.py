#! /usr/bin/env python3
import json
import os


def rkt_path_d(path):
    rkt_data = "/tmp/rkt-data"
    data = {
        "rktKind": "paths",
        "rktVersion": "v1",
        "data": rkt_data,
        "stage1-images": "%s/rkt" % path
    }
    try:
        os.makedirs("%s/paths.d/" % path)
    except OSError:
        pass
    try:
        os.makedirs(rkt_data)
    except OSError:
        pass

    with open("%s/paths.d/paths.json" % path, "w") as f:
        json.dump(data, f)


def rkt_stage1_d(path):
    data = {
        "rktKind": "stage1",
        "rktVersion": "v1",
        "name": "coreos.com/rkt/stage1-coreos",
        "version": "v1.27.0",
        "location": "%s/rkt/stage1-coreos.aci" % path
    }
    try:
        os.makedirs("%s/stage1.d/" % path)
    except OSError:
        pass

    with open("%s/stage1.d/coreos.json" % path, "w") as f:
        json.dump(data, f)


def dgr_config(path):
    data = [
        "targetWorkDir: %s/target" % path,
        "rkt:",
        "  path: %s/rkt/rkt" % path,
        "  insecureOptions: [http, image]",
        "  dir: %s/data" % path,
        "  localConfig: %s" % path,
        "  systemConfig: %s" % path,
        "  userConfig: %s" % path,
        "  trustKeysFromHttps: false",
        "  noStore: false",
        "  storeOnly: false",
        "push:",
        '  url: "http://enjoliver.local"',
    ]
    with open("%s/config.yml" % path, "w") as f:
        f.write("\n".join(data) + "\n")


def acserver_config(path):
    data = [
        "api:",
        "  serverName: enjoliver.local",
        "  port: 80",
        "storage:",
        "  unsigned: true",
        "  allowOverride: true",
        '  rootPath: %s/acserver.d' % path,
    ]
    with open("%s/ac-config.yml" % path, "w") as f:
        f.write("\n".join(data) + "\n")
    with open("/etc/hosts") as f:
        for l in f:
            if "enjoliver.local" in l:
                return
    try:
        with open("/etc/hosts", 'a') as f:
            f.write("172.20.0.1 enjoliver.local # added by %s\n" % os.path.abspath(__file__))
    except IOError:
        print("/etc/hosts ignore: run as sudo")


if __name__ == "__main__":
    pwd = os.path.dirname(os.path.abspath(__file__))
    rkt_path_d(pwd)
    rkt_stage1_d(pwd)
    dgr_config(pwd)
    acserver_config(pwd)
