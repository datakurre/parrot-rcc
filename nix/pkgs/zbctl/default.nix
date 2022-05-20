{ buildGoModule, fetchFromGitHub }:

buildGoModule rec {
  name = "zbctl-${version}";
  version = "v8.0.2";
  src = fetchFromGitHub {
    owner = "camunda";
    repo = "zeebe";
    rev = "clients/go/${version}";
    sha256 = "1l4gs8ha0h97gqi14cr7psv5dgzr2gv0q21z7dcmkr7rpsf43xn4";
  };
  modRoot = "./clients/go/cmd/zbctl";
  vendorSha256 = "0sjjj9z1dhilhpc8pq4154czrb79z9cm044jvn75kxcjv6v5l2m5";
  preBuild = ''
    source $stdenv/setup
    patchShebangs build.sh
  '';
  doCheck = false;  # requires docker
}
