SHELL := /usr/bin/env bash

.PHONY: all
all: format

env: poetry.lock
	nix build .#env -o env

.PHONY: format
format:
	PYTHONPATH= black src
	isort src

.PHONY: shell
shell:
	nix develop

###

.PHONY: nix-%
nix-%:
	nix develop $(NIX_OPTIONS) --command $(MAKE) $*
