package main

import (
	"flag"
	"github.com/golang/glog"
	"net/http"
	"os"
	"sync"
	"time"
)

const (
	ControlPlaneFlagName = "control-plane"
	RktFetchInsecure     = "rkt-fetch-insecure"
)

type Runtime struct {
	HttpLivenessProbes    []HttpLivenessProbe
	LocksmithEndpoint     string
	LocksmithLock         string
	RestartKubernetesLock sync.RWMutex
}

func main() {
	glog.Infof("starting node-agent")
	flag.Bool(ControlPlaneFlagName, false, "Is control-plane node")
	flag.Bool(RktFetchInsecure, true, "rkt fetch --insecure-options=all")

	flag.Parse()
	flag.Lookup("alsologtostderr").Value.Set("true")

	p, err := getHttpLivenessProbesToQuery()
	if err != nil {
		glog.Errorf("fail to get HttpLivenessProbes to query: %s", err)
		os.Exit(2)
	}

	locksmithEndpoint, locksmithLockName, err := getLocksmithConfig(p)
	if err != nil {
		glog.Errorf("fail to get locksmith endpoint in probes: %s", err)
		os.Exit(3)
	}

	run := &Runtime{
		p,
		locksmithEndpoint,
		locksmithLockName,
		sync.RWMutex{},
	}
	http.DefaultClient.Timeout = time.Second * 2
	http.HandleFunc("/healthz", run.handlerHealthz)
	http.HandleFunc("/version", run.handlerVersion)
	http.HandleFunc("/hack/rkt/fetch", run.handlerHackRktFetch)
	http.HandleFunc("/hack/systemd/restart/kubernetes", run.handlerHackSystemdRestartKubernetesStack)
	glog.Fatal(http.ListenAndServe("0.0.0.0:8000", nil))
}
