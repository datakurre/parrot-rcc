# https://github.com/nmattia/niv
{ sources ? import ./sources.nix
, nixpkgs ? sources."nixpkgs"
}:

let

  overlay = _: pkgs: rec {
    jupyterLiteEnv = pkgs.callPackage ./pkgs/jupyterLiteEnv{};
    poetry2nix = pkgs.callPackage ./pkgs/poetry2nix { inherit nixpkgs; };
    rcc = pkgs.callPackage ./pkgs/rcc/rcc.nix {};
    rccFHSUserEnv = pkgs.callPackage ./pkgs/rcc {};
    zbctl = pkgs.callPackage ./pkgs/zbctl {};
  };

  pkgs = import nixpkgs {
    overlays = [ overlay ];
  };

in pkgs
