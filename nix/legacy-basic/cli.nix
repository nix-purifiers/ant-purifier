# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  nix,
  ant,
  legacySdk,
  legacyRuntime,
  nixpkgsSrc,
  purifierSrc,
}:
let
  classpath = "${legacyRuntime.collectorJar}:${legacySdk.ivyJar}:${ant}/share/ant/lib/*:${legacySdk.home}/lib/tools.jar";
in
stdenvNoCC.mkDerivation {
  pname = "ant-purifier";
  version = "0.1.0-legacy-basic";
  src = ../..;
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  passthru.purifierRuntime = {
    nativeProfile = "legacy-basic-v1";
    javaHome = legacySdk.home;
    ant = "${ant}/bin/ant";
    ivy = legacySdk.ivyJar;
    plugin = legacyRuntime.collectorJar;
    context = legacyRuntime.contextFile;
    properties = legacyRuntime.propertiesFile;
  };
  installPhase = ''
    mkdir -p "$out/bin" "$out/lib"
    cp -r ant_purifier ant_purifier_legacy nix "$out/lib/"
    substituteInPlace "$out/lib/nix/legacy-basic/realize.nix" \
      --replace-fail '@nixpkgs@' '${nixpkgsSrc}' \
      --replace-fail '@purifier@' '${purifierSrc}' \
      --replace-fail '@system@' '${stdenvNoCC.hostPlatform.system}'
    makeWrapper ${python3.interpreter} "$out/bin/ant-purifier" \
      --add-flags '-B -m ant_purifier_legacy' \
      --prefix PYTHONPATH : "$out/lib" \
      --prefix PATH : ${
        lib.escapeShellArg (
          lib.makeBinPath [
            nix
            ant
          ]
          + ":${legacySdk.home}/bin"
        )
      } \
      --set JAVA_HOME ${lib.escapeShellArg legacySdk.home} \
      --set-default JAVACMD ${lib.escapeShellArg legacySdk.manager.executable} \
      --set ANT_HOME ${lib.escapeShellArg "${ant}/share/ant"} \
      --set ANT_PURIFIER_STORE_DIR ${lib.escapeShellArg builtins.storeDir} \
      --set ANT_PURIFIER_ANT ${lib.escapeShellArg "${ant}/bin/ant"} \
      --set ANT_PURIFIER_JAVA ${lib.escapeShellArg legacySdk.manager.executable} \
      --set ANT_PURIFIER_ANT_HOME ${lib.escapeShellArg "${ant}/share/ant"} \
      --set ANT_PURIFIER_LEGACY_CONTEXT ${lib.escapeShellArg "${legacyRuntime.contextFile}"} \
      --set ANT_PURIFIER_LEGACY_PROPERTIES ${lib.escapeShellArg "${legacyRuntime.propertiesFile}"} \
      --set ANT_PURIFIER_LOCK_CLASSPATH ${lib.escapeShellArg classpath} \
      --set ANT_PURIFIER_REALIZE "$out/lib/nix/legacy-basic/realize.nix" \
      --set ANT_PURIFIER_LEGACY_RUNTIME "$out"
    makeWrapper "$out/bin/ant-purifier" "$out/bin/ant" --add-flags 'native --'
  '';
  meta = {
    description = "Explicit basic legacy Ant/Ivy workflow using a source-owned JVM SDK";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "ant-purifier";
  };
}
