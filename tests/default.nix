# SPDX-License-Identifier: MIT
{ pkgs, self }:
let
  project = pkgs.ant-purifier.buildAntProject {
    src = ../examples/minimal;
    buildTargets = [ "test" ];
    publishTarget = "publish";
  };
in
{
  composition-provider = import ./composition-provider.nix {
    inherit pkgs;
    purifier = import (self.inputs.purifier + "/nix/lib") { inherit (pkgs) lib; };
  };
  cli = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
  plugin = self.packages.${pkgs.stdenv.hostPlatform.system}.plugin;
  environment = project.packages.environment;
  project = project.tests;
  release = project.release;
  mavenProjection = project.projections.maven;
  ivyProjection = project.projections.ivy;
  nativeConsumer = import ./consumer.nix { inherit pkgs project; };
  editor = import ./editor.nix { inherit pkgs project; };
}
