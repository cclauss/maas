#
# Makefile to build the machine-resources binary on all relevant platforms.
#

ARCHES := amd64 386 arm arm64 ppc64le s390x
BINARIES = $(ARCHES)

.DEFAULT_GOAL := build

deps:
	go get -u -v github.com/lxc/lxd/lxd/resources
.PHONY: deps

build: $(BINARIES)
.PHONY: build

$(BINARY_PREFIX)%: %
	@true  # to force the rule to execute

$(ARCHES): deps
	GOARCH=$@ go build -o $@ machine-resources.go
.PHONY: $(ARCHES)

clean:
	rm -f $(BINARIES)
.PHONY: clean
