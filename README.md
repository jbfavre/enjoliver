# Enjoliver 

Travis-ci (com / org)

* [![Build Status](https://travis-ci.com/JulienBalestra/enjoliver-private.svg?token=ZwLEpiSqDoYCiBWcDCqE&branch=master)](https://travis-ci.com/JulienBalestra/enjoliver-private)  
* [![Build Status](https://travis-ci.com/JulienBalestra/enjoliver-release.svg?token=ZwLEpiSqDoYCiBWcDCqE&branch=master)](https://travis-ci.com/JulienBalestra/enjoliver-release) 
* [![Build Status](https://travis-ci.com/JulienBalestra/enjoliver.svg?token=ZwLEpiSqDoYCiBWcDCqE&branch=master)](https://travis-ci.com/JulienBalestra/enjoliver)  
* [![Build Status](https://travis-ci.org/JulienBalestra/enjoliver.svg?branch=master)](https://travis-ci.org/JulienBalestra/enjoliver) 


## Description

Deploy and maintain an usable Kubernetes cluster.

The Kubernetes Kubelet container runtime is `rkt`.

Kubernetes Apiserver, controller, scheduler and Apiserver proxies are deployed as `Pod` with Kubelet.  

Vault, Kubernetes and Fleet have dedicated etcd clusters.

Vault pki backend secure the following components:

* etcd for fleet
    * peer
    * client
* etcd for kubernetes
    * peer
    * client
* kube-apiserver
    * x509 authentication for kubectl  
    * service accounts
* kube-controller-manager
    * cluster signing key
* kubelet

Each etcd cluster supports automatic members replacement.

The configuration of each host is managed by Ignition.

During the lifecycle of the Kubernetes cluster, rolling updates are **fast** and fully controlled.
* The rolling update of the configuration changes are granted by Enjoliver API `/lifecycle/rolling/mac=00:01:02:03:04:05`
* The semaphore is managed by locksmith.
* The Ignition is applied after a fast systemd-kexec or normal reboot

Each node can be re-installed and re-join the cluster.

## Cluster topology

![cp](docs/topology.jpg)

## Baremetal iPXE

![machine-boot](docs/machine-boot.jpg)

## Current Stack

### Upstream

* [etcd](https://github.com/coreos/etcd/releases)	
* [cni](https://github.com/containernetworking/cni/releases)
* [rkt](https://github.com/rkt/rkt/releases)
* [kubernetes](https://github.com/kubernetes/kubernetes/releases)
    * PR: ~/aci/aci-hyperkube/patches
* [vault](https://github.com/hashicorp/vault/releases)
* [Container Linux](https://coreos.com/releases)

### Stick

* [fleet](https://github.com/coreos/fleet/releases/tag/v1.0.0)


## Enjoliver Architecture


![enjoliver-archi](docs/enjoliver-architecture.jpg)

### Matchbox

[Official project](https://github.com/coreos/matchbox#matchbox)

Enjoliver use 3 profiles in matchbox
1) discovery
2) etcd-member-kubernetes-control-plane
2) kubernetes-node

##### Discovery

The discovery allows to boot in memory CoreOS instances to proceed of:
 
1) sending the facts of the machine (MAC address, IP address, ...)
2) fetch his role
3) disk installation


For matchbox, the discovery profile has one group without any selector.

In this case, all un-selected machines will match this profile by default.
This profile has one associated group, with 2 metadata entries:

1) api uri
2) ssh-key

##### etcd-member-kubernetes-control-plane

This role is for:
1) etcd members
    * vault
    * fleet
    * kubernetes
2) vault
3) kube-{apiserver, controller-manager, scheduler}

This role need to be bootstrapped as 3, 5, ... instances and is needed by all the other nodes.

To solve this problem, the Enjoliver Scheduler will apply the roles only if the required number of instances are available.

So, if the cluster size is 5, the first 5 instances in discovery will get this role.


##### kubernetes-node

This role is a standard worker (Kubernetes node)

All additional nodes over the wanted **etcd-member-kubernetes-control-plane** requirements will become **kubernetes-node**


### Enjoliver API

Everything has to go through this endpoint.

This is the available routes:

    [
      "/", 
      "/apidocs/<path:filename>", 
      "/assets", 
      "/assets/<path:path>", 
      "/backup/db", 
      "/boot.ipxe", 
      "/boot.ipxe.0", 
      "/configs", 
      "/discovery", 
      "/discovery/ignition-journal", 
      "/discovery/ignition-journal/<string:uuid>", 
      "/discovery/ignition-journal/<string:uuid>/<string:boot_id>", 
      "/discovery/interfaces", 
      "/healthz", 
      "/ignition", 
      "/install-authorization/<string:request_raw_query>", 
      "/ipxe", 
      "/lifecycle/coreos-install", 
      "/lifecycle/coreos-install/<string:status>/<string:request_raw_query>", 
      "/lifecycle/ignition", 
      "/lifecycle/ignition/<string:request_raw_query>", 
      "/lifecycle/rolling", 
      "/lifecycle/rolling/<string:request_raw_query>", 
      "/metadata", 
      "/scheduler", 
      "/scheduler/<string:role>", 
      "/scheduler/available", 
      "/scheduler/ip-list/<string:role>", 
      "/shutdown", 
      "/spec", 
      "/specs", 
      "/static/<path:filename>", 
      "/ui", 
      "/ui/view/machine"
    ]


A Swagger UI is available at `/apidocs/index.html`

![swagger](docs/swagger.png)

The Enjoliver API is backed by a SQL database.

![sql](docs/sql.jpg)

### Sync

Matchbox store his state inside filesystem folders (JSON).

To keep it up-to-date, the sync process query the Enjoliver API `/scheduler/...`

In this current topology, the matchbox state isn't critical and can be regenerated at any time.

### Scheduler

By querying the Enjoliver API `/scheduler/available`, the scheduler can affect discovery instances to a role.


### Production - Baremetal

You can take as example the `aci/aci-enjoliver` to see how the rkt container is built with `dgr`

Fulfill the configuration file `app/configs.yaml`

About the aci, you need pass all the `dgr test` or adapt the ignition files.
 
### Development - Local KVM

This part will soon have a better documentation.

If you still want to try you can follow this steps:

Requirements:

* **Linux** with filesystem overlay for `dgr`
* See `apt.sh` for the needed packages or `sudo make apt`
* See `.travis.yml` as a setup example & unit / integration tests

All in one dev setup:


    sudo MY_USER=julien make dev_setup
    
    
Start an interactive Kubernetes deployment of 2 nodes:

    # Generate ssh keys
    make -C app/tests testing.id_rsa
    
    # Start the deployment
    sudo make -C app/tests check_euid_it_plans_enjolivage_disk_2_nodes


The enjoliver API is available on `127.0.0.1:5000`, the user interface is behind the `/ui`

    
At the end of the setup, a kubectl proxy is running on `127.0.0.1:8001`
 
 

    ./hyperkube/hyperkube kubectl -s 127.0.0.1:8001 get cs
    NAME                 STATUS    MESSAGE              ERROR
    scheduler            Healthy   ok                   
    controller-manager   Healthy   ok                   
    etcd-0               Healthy   {"health": "true"}
    
    ./hyperkube/hyperkube kubectl -s 127.0.0.1:8001 get po --all-namespaces
    NAMESPACE     NAME                                  READY     STATUS    RESTARTS   AGE
    default       httpd-daemonset-265lc                 1/1       Running   0          2m
    default       httpd-daemonset-3229856519-n3dqt      1/1       Running   0          2m
    default       httpd-daemonset-55swx                 1/1       Running   0          2m
    kube-system   kube-apiserver-172.20.0.30            1/1       Running   0          2m
    kube-system   kube-apiserver-172.20.0.90            1/1       Running   0          3m
    kube-system   kube-controller-manager-172.20.0.90   1/1       Running   0          3m
    kube-system   kube-scheduler-172.20.0.90            1/1       Running   0          3m   
    

Connect inside with `ssh`:


    ./app/s.sh