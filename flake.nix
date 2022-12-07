{
  description = "parrot-rcc";

  # Flakes
  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/release-22.11";
  inputs.poetry2nix = { url = "github:nix-community/poetry2nix"; inputs.nixpkgs.follows = "nixpkgs"; };

  # Sources
  inputs.rcc = { url = "github:robocorp/rcc/65cb4b6f9fb30cffd61c3f0d3617d33b51390c61"; flake = false; }; # v11.31.2
  inputs.zbctl = { url = "github:camunda/zeebe/clients/go/v8.1.3"; flake = false; };

  # Systems
  outputs = { self, nixpkgs, flake-utils, poetry2nix, rcc, zbctl }:
    {
      # Nixpkgs overlay providing the application
      overlay = nixpkgs.lib.composeManyExtensions [
        poetry2nix.overlay
        (final: prev: {
          # The application
          myapp = prev.poetry2nix.mkPoetryApplication {
            projectDir = self;
            preferWheels = true;
            overrides = prev.poetry2nix.overrides.withDefaults (self: super: { 
              "file-magic" = super."file-magic".overridePythonAttrs(old: {
                nativeBuildInputs = old.nativeBuildInputs ++ [ self.setuptools ];
              });
            });
          };
        })
      ];
    } // (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ self.overlay ];
        };
      in
      {
        # Release
        apps.myapp = pkgs.myapp;
        defaultApp = pkgs.myapp;
        packages.default = pkgs.myapp;

        # Development
        packages.rcc = pkgs.callPackage ./pkgs/rcc/rcc.nix { src = rcc; version = "v11.31.2"; };
        packages.rccFHSUserEnv = pkgs.callPackage ./pkgs/rcc { src = rcc; version = "v11.31.2"; };
        packages.zbctl = pkgs.callPackage ./pkgs/zbctl { src = zbctl; version = "v8.1.3"; };
        packages.env = pkgs.poetry2nix.mkPoetryEnv {
          projectDir = self;
          preferWheels = true;
          overrides = pkgs.poetry2nix.overrides.withDefaults (self: super: { 
            "file-magic" = super."file-magic".overridePythonAttrs(old: {
              nativeBuildInputs = old.nativeBuildInputs ++ [ self.setuptools ];
            });
          });
        };
        devShell = pkgs.mkShell {
          buildInputs = with pkgs; [
            (python310.withPackages (ps: with ps; [
              black
              isort
              poetry
            ]))
            entr
            gnumake
            self.packages.${system}.rccFHSUserEnv
            self.packages.${system}.zbctl
            twine
          ];
          shellHook = ''
            export PATH=${self.packages.${system}.env}/bin:$PATH
            export PYTHONPATH=$(pwd)/src
          '';
        };
      }));
}
