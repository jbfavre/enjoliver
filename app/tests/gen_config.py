#! /usr/bin/env python
import json
import os


def rkt_path_d(full_path):
    data = {
        "rktKind": "paths",
        "rktVersion": "v1",
        "data": "%s/rkt_dir/data" % full_path,
        "stage1-images": "%s/rkt_dir" % full_path
    }
    with open("%s/paths.d/paths.json" % full_path, "w") as f:
        json.dump(data, f)


if __name__ == "__main__":

    CWD = os.path.dirname(os.path.abspath(__file__))

    print "Generate config with CWD=%s" % CWD

    rkt_path_d(CWD)