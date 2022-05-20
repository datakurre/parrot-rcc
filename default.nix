{ pkgs ? import ./nix {}
, sources ? import ./nix/sources.nix
}:

pkgs.poetry2nix.mkPoetryApplication {
  projectDir = ./.;
  overrides = pkgs.poetry2nix.overrides.withDefaults(self: super: {
     pyzeebe = super.pyzeebe.overridePythonAttrs(old: {
       nativeBuildInputs = [ self.poetry ];
     });
  });
}
