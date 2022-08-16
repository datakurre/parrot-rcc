{ buildGoModule, fetchFromGitHub }:

buildGoModule rec {
  name = "zbctl-${version}";
  version = "v8.0.5";
  src = fetchFromGitHub {
    owner = "camunda";
    repo = "zeebe";
    rev = "clients/go/${version}";
    sha256 = "sha256-57mD5u87h/Go78en9B/YJXYJdwlbhpQSSq8vM+Kspk8=";
  };
  modRoot = "./clients/go/cmd/zbctl";
  vendorSha256 = "0sjjj9z1dhilhpc8pq4154czrb79z9cm044jvn75kxcjv6v5l2m5";
  preBuild = ''
    source $stdenv/setup
    patchShebangs build.sh
  '';
  doCheck = false;  # requires docker
}
