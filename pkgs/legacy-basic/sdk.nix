# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  legacyJvmAdapter,
  sdkContract,
  ant,
  apacheIvy,
}:
let
  adapter =
    if legacyJvmAdapter == null then
      throw "ant-purifier: legacy-basic-v1 requires a live source-owned JVM SDK adapter"
    else
      legacyJvmAdapter;
  identity = import (sdkContract + "/nix/lib/jvm-sdk-identity.nix") { inherit lib; } {
    inherit (adapter) sdk home manager;
    system = stdenvNoCC.hostPlatform.system;
  };
  antJar = "${ant}/share/ant/lib/ant.jar";
  ivyJar = toString apacheIvy;
in
assert
  stdenvNoCC.hostPlatform.system == "x86_64-linux"
  || throw "ant-purifier: legacy-basic-v1 is implemented only on x86_64-linux";
assert
  identity.managerIdentity != null
  || throw "ant-purifier: legacy-basic-v1 requires an explicit manager executable and runtime home";
{
  inherit (adapter) sdk home manager;
  inherit identity antJar ivyJar;
  context = {
    version = "ant-legacy-runtime-context-v1";
    sdk = identity.payload;
    sdkIdentityHash = identity.identityHash;
    manager = identity.managerIdentity.payload;
    managerIdentityHash = identity.managerIdentity.identityHash;
    contract = {
      source = toString sdkContract;
      sourceContext = builtins.getContext (toString sdkContract);
    };
    ant = {
      output = toString ant;
      outputContext = builtins.getContext (toString ant);
      jar = antJar;
      jarContext = builtins.getContext antJar;
      version = ant.version;
    };
    ivy = {
      output = ivyJar;
      outputContext = builtins.getContext ivyJar;
      version = apacheIvy.version;
    };
  };
  closureInputs = identity.closureInputs ++ [
    ant
    antJar
    apacheIvy
    sdkContract
  ];
}
