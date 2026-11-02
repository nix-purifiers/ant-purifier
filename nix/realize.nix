# SPDX-License-Identifier: MIT
{
  project,
  lockFile,
  ivyLock,
  ivyFile,
  buildFile,
  target,
}:
let
  pkgs = import (builtins.toPath "@nixpkgs@") { };
  purifier = import (builtins.toPath "@purifier@/nix/lib") { inherit (pkgs) lib; };
  apacheIvy = builtins.toPath "@ivy@";
  plugin = builtins.toPath "@plugin@";
  lock = (import ./read-lock.nix { inherit (pkgs) lib; }) {
    src = /. + project;
    lockFile = /. + lockFile;
    ivyLock = /. + ivyLock;
    ivyFile = /. + ivyFile;
    buildFile = /. + buildFile;
  };
  args = {
    src = /. + project;
    lockFile = /. + lockFile;
    ivyLock = /. + ivyLock;
    ivyFile = /. + ivyFile;
    buildFile = /. + buildFile;
  };
in
if target == "environment" then
  pkgs.callPackage ./environment.nix { inherit purifier; } { inherit lock; }
else if target == "runtime" then
  pkgs.runCommand "ant-purifier-runtime" { } ''ln -s @runtime@ "$out"''
else if target == "release" then
  (pkgs.callPackage ./build-project.nix { inherit purifier apacheIvy plugin; } args).release
else
  throw "ant-purifier: unknown realization target ${target}"
