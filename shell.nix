{ pkgs ? import ./nix {}
, sources ? import ./nix/sources.nix
}:

(pkgs.poetry2nix.mkPoetryEnv {
  preferWheels = true;
  projectDir = ./.;
  overrides = pkgs.poetry2nix.overrides.withDefaults(self: super: {
     pyzeebe = super.pyzeebe.overridePythonAttrs(old: {
       nativeBuildInputs = [ self.poetry ];
     });
  });
  editablePackageSources = {
    parrot-rcc = ./src;
  };
}).env.overrideAttrs(old: {
  buildInputs = with pkgs; [
    python3Packages.isort
    black
    gnumake
    niv
    poetry
    poetry2nix.cli
    rccFHSUserEnv
    twine
    zbctl
    entr
  ];
})
