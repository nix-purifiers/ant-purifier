# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/ant-purifier.lock.json",
  ...
}@args:
let
  keysAre =
    value: names:
    builtins.isAttrs value && builtins.attrNames value == builtins.sort builtins.lessThan names;
  hash = value: builtins.isString value && builtins.match "[0-9a-f]{64}" value != null;
  digest = value: builtins.hashString "sha256" (builtins.toJSON value);
  path =
    value:
    builtins.isString value
    && lib.hasPrefix "${builtins.storeDir}/" value
    && builtins.match ".*[[:cntrl:]].*" value == null
    && lib.all (p: p != "" && p != "." && p != "..") (
      lib.splitString "/" (lib.removePrefix "${builtins.storeDir}/" value)
    );
  contextMap =
    value:
    builtins.isAttrs value
    && value != { }
    && lib.all (
      name:
      path name
      && builtins.isAttrs value.${name}
      && value.${name} != { }
      && lib.all (
        key:
        builtins.elem key [
          "path"
          "allOutputs"
          "outputs"
        ]
      ) (builtins.attrNames value.${name})
      && (!(value.${name} ? path) || value.${name}.path == true)
      && (!(value.${name} ? allOutputs) || value.${name}.allOutputs == true)
      && (
        !(value.${name} ? outputs)
        || (
          builtins.isList value.${name}.outputs
          && value.${name}.outputs != [ ]
          && lib.all builtins.isString value.${name}.outputs
        )
      )
    ) (builtins.attrNames value);
  sdkOK =
    value:
    keysAre value [
      "version"
      "output"
      "home"
      "outputContext"
      "homeContext"
    ]
    && value.version == "sdk-output-home-context-v1"
    && path value.output
    && path value.home
    && contextMap value.outputContext
    && contextMap value.homeContext;
  managerOK =
    value:
    keysAre value [
      "version"
      "sdkIdentity"
      "executable"
      "runtimeHome"
      "executableContext"
      "runtimeHomeContext"
    ]
    && value.version == "jvm-manager-executable-runtime-home-v1"
    && hash value.sdkIdentity
    && path value.executable
    && path value.runtimeHome
    && contextMap value.executableContext
    && contextMap value.runtimeHomeContext;
  jarOK =
    value:
    keysAre value [
      "output"
      "outputContext"
      "jar"
      "jarContext"
      "version"
    ]
    && path value.output
    && contextMap value.outputContext
    && path value.jar
    && contextMap value.jarContext
    && builtins.isString value.version
    && value.version != "";
  runtimeOK =
    value:
    keysAre value [
      "version"
      "sdk"
      "sdkIdentityHash"
      "manager"
      "managerIdentityHash"
      "contract"
      "ant"
      "ivy"
      "collector"
    ]
    && value.version == "ant-legacy-runtime-context-v1"
    && sdkOK value.sdk
    && managerOK value.manager
    && value.sdkIdentityHash == digest value.sdk
    && value.manager.sdkIdentity == value.sdkIdentityHash
    && value.managerIdentityHash == digest value.manager
    && jarOK value.ant
    && jarOK value.collector
    && keysAre value.contract [
      "source"
      "sourceContext"
    ]
    && path value.contract.source
    && contextMap value.contract.sourceContext
    && keysAre value.ivy [
      "output"
      "outputContext"
      "version"
    ]
    && path value.ivy.output
    && contextMap value.ivy.outputContext
    && builtins.isString value.ivy.version
    && value.ivy.version != "";
  parsed =
    if builtins.pathExists lockFile then builtins.fromJSON (builtins.readFile lockFile) else { };
  data = if builtins.isAttrs parsed then parsed else { };
  payloadName = builtins.baseNameOf (toString lockFile) + ".payload.json";
  payloadFile = builtins.dirOf lockFile + "/${payloadName}";
  outerOK =
    keysAre data [
      "version"
      "profile"
      "payloadFile"
      "payloadHash"
      "runtimeContext"
      "runtimeHash"
      "observed"
      "contentHash"
    ]
    && builtins.isInt data.version
    && data.version == 2
    && data.profile == "legacy-basic-v1"
    && data.payloadFile == payloadName
    && hash data.payloadHash
    && hash data.contentHash
    && data.contentHash == digest (removeAttrs data [ "contentHash" ])
    && runtimeOK data.runtimeContext
    && data.runtimeHash == digest data.runtimeContext
    && keysAre data.observed [
      "contextHash"
      "sdkIdentity"
      "managerIdentity"
      "executable"
      "runtimeHome"
      "javaVersion"
      "antVersion"
      "ivyVersion"
      "antJar"
      "ivyJar"
      "collectorJar"
    ]
    && lib.all (v: builtins.isString v && v != "") (builtins.attrValues data.observed)
    && data.observed.contextHash == data.runtimeHash
    && data.observed.sdkIdentity == data.runtimeContext.sdkIdentityHash
    && data.observed.managerIdentity == data.runtimeContext.managerIdentityHash
    && data.observed.antVersion == data.runtimeContext.ant.version
    && data.observed.ivyVersion == data.runtimeContext.ivy.version
    && lib.all (name: path data.observed.${name}) [
      "executable"
      "runtimeHome"
      "antJar"
      "ivyJar"
      "collectorJar"
    ];
  payload =
    if outerOK && builtins.pathExists payloadFile then
      builtins.fromJSON (builtins.readFile payloadFile)
    else
      { };
  payloadOK =
    keysAre payload [
      "version"
      "antVersion"
      "ivyVersion"
      "javaVersion"
      "resolverVersion"
      "nativeHash"
      "ivyHash"
      "buildHash"
      "inputs"
      "ivyFile"
      "buildFile"
      "resolveTarget"
      "properties"
      "modules"
      "artifacts"
      "metadata"
      "sourceRoots"
      "contentHash"
    ]
    && payload.version == 1
    && payload.metadata == [ ]
    && payload.antVersion == data.runtimeContext.ant.version
    && payload.ivyVersion == data.runtimeContext.ivy.version
    && payload.resolverVersion == data.runtimeContext.collector.version
    && payload.javaVersion == data.observed.javaVersion;
  base =
    if outerOK && payloadOK then
      (import ../read-lock.nix { inherit lib; }) (args // { lockFile = payloadFile; })
    else
      {
        purifier = "ant-purifier";
        entries = [ ];
        problems = [ ];
        modules = [ ];
        artifacts = [ ];
        sourceRoots = [ ];
        projectInputs = [ ];
      };
  problems =
    if !outerOK then
      [ "invalid or unsupported closed legacy basic lock" ]
    else if
      !builtins.pathExists payloadFile || builtins.hashFile "sha256" payloadFile != data.payloadHash
    then
      [ "legacy payload changed since capture" ]
    else if !payloadOK then
      [ "invalid legacy graph payload or native origin metadata" ]
    else
      base.problems;
in
base
// {
  inherit problems;
  nativeProfile = "legacy-basic-v1";
  legacyRuntimeContext = data.runtimeContext or null;
  legacyRuntimeHash = data.runtimeHash or null;
  legacyObserved = data.observed or null;
  legacyProperties = payload.properties or [ ];
  # This profile exposes dependencies and a source/class tree, not publications.
  outputs = { };
  mavenRuntimeComplete = false;
  projectInputs = [ ];
}
