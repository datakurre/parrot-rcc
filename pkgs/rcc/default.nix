{ callPackage, buildFHSUserEnv, buildGoPackage, go-bindata, rake, zip, micromamba
, which, cacert, dbus-glib, libGL, name ? "rcc", runScript ? "rcc", src, version }:

let rcc = callPackage ./rcc.nix {
  inherit buildGoPackage go-bindata rake zip src version;
};

in buildFHSUserEnv {
  targetPkgs = pkgs: (with pkgs; [
    micromamba
    rcc
  ]);
  # these are not easily available at Conda
  profile = ''
    export LD_LIBRARY_PATH="${dbus-glib}/lib:${libGL}/lib"
  '';
  inherit name runScript;
}
