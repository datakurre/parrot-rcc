{ pkgs ? import ./nix {}
, sources ? import ./nix/sources.nix
}:

(pkgs.poetry2nix.mkPoetryEnv {
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
  buildInput = with pkgs; [
    black
    gnumake
    niv
    poetry
    poetry2nix.cli
    rccFHSUserEnv
    twine
    zbctl
  ];
})
