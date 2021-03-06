CWD=$(shell pwd)
CHECK=check
CHECK_EUID=check_euid
CHECK_EUID_KVM_PLAYER=check_euid_kvm_player
SHELL=bash
MY_USER=${SUDO_USER}

.PHONY:

default: help

help:
	@echo ----------------------
	@echo Prepare:
	@echo sudo make apt
	@echo ----------------------
	@echo All in one for local usage:
	@echo sudo MY_USER= make dev_setup
	@echo
	@echo All in one for production usage:
	@echo sudo MY_USER= make prod_setup
	@echo ----------------------
	@echo Testing:
	@echo make $(CHECK)
	@echo
	@echo Ready for KVM:
	@echo sudo make $(CHECK_EUID_KVM_PLAYER)
	@echo
	@echo KVM - long:
	@echo sudo make $(CHECK_EUID)
	@echo ----------------------
	@echo Release:
	@echo sudo make aci_enjoliver
	@echo ----------------------

apt:
	test $(shell id -u -r) -eq 0
	DEBIAN_FRONTEND=noninteractive INSTALL="-y" ./apt.sh

acserver:
	test $(shell id -u -r) -eq 0
	$(MAKE) -C $(CWD)/runtime/ create_rack0
	./runtime/run_acserver.py &

aci_core: acserver
	$(MAKE) -C aci core
	pkill -F $(CWD)/runtime/acserver.pid || true

aci: acserver
	$(MAKE) -C aci kube_deps
	pkill -F $(CWD)/runtime/acserver.pid || true

assets:
	$(MAKE) -C matchbox/assets/discoveryC
	$(MAKE) -C matchbox/assets/enjoliver-agent

remove_aci:
	test $(shell id -u -r) -eq 0
	$(MAKE) -C runtime gc
	$(MAKE) -C runtime gci
	rm -Rf runtime/target/*
	rm -Rf runtime/acserver.d/enjoliver.local/*

clean_after_assets:
	$(MAKE) -C discoveryC clean
	$(MAKE) -C enjoliver-agent clean

check_clean:
	$(MAKE) -C enjoliver-testsuite/ fclean

clean: clean_after_assets check_clean
	rm -Rf runtime/acserver.d/*
	rm -Rf runtime/target/*

$(CHECK):
	$(MAKE) -C discoveryC/ $(CHECK)
	$(MAKE) -C enjoliver-agent/ $(CHECK)
	$(MAKE) -C enjoliver-testsuite/ $(CHECK)

$(CHECK_EUID): validate
	test $(shell id -u -r) -eq 0
	$(MAKE) -C enjoliver-testsuite/ $(CHECK_EUID)

$(CHECK_EUID_KVM_PLAYER):
	test $(shell id -u -r) -eq 0
	$(MAKE) -C enjoliver-testsuite/ $(CHECK_EUID_KVM_PLAYER)

submodules:
	git submodule update --init --recursive

validate:
	ENJOLIVER_CONFIG=./enjoliver-api/enjoliver.yaml python3 validate.py

dev_setup_runtime: submodules
	$(MAKE) -C runtime dev_setup

prod_setup_runtime:
	$(MAKE) -C runtime prod_setup

front:
	$(MAKE) -C enjoliver-ui

config:
	mkdir -pv $(HOME)/.config/enjoliver
	touch $(HOME)/.config/enjoliver/config.env
	touch $(HOME)/.config/enjoliver/config.json

container_linux: acserver
	$(MAKE) -C aci/aci-container-linux install
	./runtime/runtime.rkt run --set-env=COMMIT_ID=$(shell git log --pretty=format:'%h' -n 1) \
	  --volume enjoliver,kind=host,source=$(CWD),readOnly=false \
      --stage1-path=$(CWD)/runtime/rkt/stage1-fly.aci --insecure-options=all \
      --interactive enjoliver.local/container-linux:latest
	pkill -F runtime/acserver.pid || true

dev_setup:
	echo "Need MY_USER for non root operations and root for dgr"
	test $(MY_USER)
	test $(shell id -u -r) -eq 0
	chown -R $(MY_USER): $(CWD)
	su -m $(MY_USER) -c "make -C $(CWD) submodules"
	su -m $(MY_USER) -c "make -C $(CWD) dev_setup_runtime"
	su -m $(MY_USER) -c "make -C $(CWD)/enjoliver-testsuite testing.id_rsa"
	su -m $(MY_USER) -c "make -C $(CWD) front"
	su -m $(MY_USER) -c "make -C $(CWD) assets"
	$(MAKE) -C $(CWD) aci
	$(MAKE) -C $(CWD) container_linux
	su -m $(MY_USER) -c "make -C $(CWD) validate"
	su -m $(MY_USER) -c "make -C $(CWD) config"
	chown -R $(MY_USER): $(CWD)

prod_setup:
	$(MAKE) -C $(CWD) submodules
	$(MAKE) -C $(CWD) prod_setup_runtime
	$(MAKE) -C $(CWD) front

