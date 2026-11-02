# SPDX-License-Identifier: MIT
{
  description = "Locked, Nix-resolved dependencies for Ant and Apache Ivy";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.purifier = {
    url = "github:nix-purifiers/purifier";
    flake = false;
  };
  outputs =
    {
      self,
      nixpkgs,
      purifier,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAll = nixpkgs.lib.genAttrs systems;
      shared = lib: import (purifier + "/nix/lib") { inherit lib; };
      overlay = final: prev: {
        ant-purifier = final.lib.makeScope final.newScope (scope: {
          apacheIvy = scope.callPackage ./nix/ivy.nix { };
          plugin = scope.callPackage ./nix/plugin.nix { };
          cli = scope.callPackage ./nix/cli.nix {
            nixpkgsSrc = nixpkgs;
            purifierSrc = purifier;
          };
          buildAntProject = scope.callPackage ./nix/build-project.nix { purifier = shared final.lib; };
        });
      };
      pkgsFor =
        system:
        import nixpkgs {
          inherit system;
          overlays = [ overlay ];
        };
    in
    {
      overlays.default = overlay;
      lib.ant-purifier.readLock = import ./nix/read-lock.nix { lib = nixpkgs.lib; };
      packages = forAll (system: {
        default = (pkgsFor system).ant-purifier.cli;
        cli = self.packages.${system}.default;
        plugin = (pkgsFor system).ant-purifier.plugin;
      });
      apps = forAll (system: {
        default = {
          type = "app";
          meta.description = "Lock and prefetch Ant and Apache Ivy dependencies";
          program = "${self.packages.${system}.default}/bin/ant-purifier";
        };
      });
      devShells = forAll (system: {
        default = (pkgsFor system).mkShell {
          packages = [
            self.packages.${system}.default
            (pkgsFor system).python3
          ];
        };
      });
      formatter = forAll (system: (pkgsFor system).nixfmt-tree);
      checks = forAll (
        system:
        import ./tests {
          pkgs = pkgsFor system;
          inherit self;
        }
      );
    };
}
