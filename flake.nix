# SPDX-License-Identifier: MIT
{
  description = "Locked, Nix-resolved dependencies for Ant and Apache Ivy";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.purifier = {
    url = "github:nix-purifiers/purifier";
    flake = false;
  };
  inputs.jvmSdkContract = {
    url = "github:nix-purifiers/purifier/f444063c705056a605583bd273cc8147f57808ee";
    flake = false;
  };
  outputs =
    {
      self,
      nixpkgs,
      purifier,
      jvmSdkContract,
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
          nativeProfile = "modern-v1";
          legacyJvmAdapter = null;
          legacySdk =
            if scope.nativeProfile == "legacy-basic-v1" then
              scope.callPackage ./pkgs/legacy-basic/sdk.nix { sdkContract = jvmSdkContract; }
            else
              null;
          apacheIvy = scope.callPackage ./pkgs/ivy/default.nix { };
          plugin =
            if scope.nativeProfile == "modern-v1" then
              scope.callPackage ./pkgs/plugin/default.nix { }
            else if scope.nativeProfile == "legacy-basic-v1" then
              scope.callPackage ./pkgs/legacy-basic/plugin.nix { }
            else
              throw "ant-purifier: unknown native profile";
          legacyRuntime =
            if scope.nativeProfile == "legacy-basic-v1" then
              scope.callPackage ./pkgs/legacy-basic/runtime.nix { }
            else
              null;
          cli =
            if scope.nativeProfile == "modern-v1" then
              scope.callPackage ./pkgs/cli/default.nix {
                nixpkgsSrc = nixpkgs;
                purifierSrc = purifier;
              }
            else if scope.nativeProfile == "legacy-basic-v1" then
              scope.callPackage ./pkgs/legacy-basic/cli.nix {
                nixpkgsSrc = nixpkgs;
                purifierSrc = purifier;
              }
            else
              throw "ant-purifier: unknown native profile";
          buildAntProject =
            if scope.nativeProfile == "modern-v1" then
              scope.callPackage ./pkgs/build-ant-project/default.nix { purifier = shared final.lib; }
            else if scope.nativeProfile == "legacy-basic-v1" then
              scope.callPackage ./pkgs/build-ant-project/legacy-basic/default.nix { purifier = shared final.lib; }
            else
              throw "ant-purifier: unknown native profile";
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
      lib.ant-purifier.readLock = import ./lib-overlays/default/read-profile-lock.nix {
        lib = nixpkgs.lib;
      };
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
