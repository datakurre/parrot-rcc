SHELL := /usr/bin/env bash
export PATH := node_modules/.bin:$(PATH)

.PHONY: all
all: format

env: poetry.lock
	nix-build -E "with import ./nix {}; poetry2nix.mkPoetryEnv { projectDir = ./.; overrides = pkgs.poetry2nix.overrides.withDefaults(self: super: { pyzeebe = super.pyzeebe.overridePythonAttrs(old: { nativeBuildInputs = [ self.poetry ]; }); }); }" -o env

.PHONY: format
format:
	black src

.PHONY: shell
shell:
	nix-shell default.nix

###

.PHONY: nix-%
nix-%:
	nix-shell $(NIX_OPTIONS) --run "$(MAKE) $*"
