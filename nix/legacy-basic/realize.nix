# SPDX-License-Identifier: MIT
# Dependency materialization only: SDK values come from the caller-built runtime.
{
  project,
  lockFile,
  ivyLock,
  ivyFile,
  buildFile,
}:
let
  pkgs = import (builtins.toPath "@nixpkgs@") { system = "@system@"; };
  purifier = import (builtins.toPath "@purifier@/nix/lib") { inherit (pkgs) lib; };
  lock = (import ./read-lock.nix { inherit (pkgs) lib; }) {
    src = /. + project;
    lockFile = /. + lockFile;
    ivyLock = /. + ivyLock;
    ivyFile = /. + ivyFile;
    buildFile = /. + buildFile;
  };
in
(pkgs.callPackage ../environment.nix { inherit purifier; }) {
  inherit lock;
  projectDependencies = [ ];
}
