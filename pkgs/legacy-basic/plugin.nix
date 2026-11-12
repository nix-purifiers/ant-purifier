# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  legacySdk,
  jdk21_headless,
}:
let
  names = builtins.attrNames (builtins.readDir ../../java-legacy/org/nixpurifiers/ant/legacy);
  sourceHash = builtins.hashString "sha256" (
    builtins.toJSON {
      sources = map (
        name: builtins.readFile (../../java-legacy/org/nixpurifiers/ant/legacy + "/${name}")
      ) names;
      context = legacySdk.context;
    }
  );
in
stdenvNoCC.mkDerivation {
  pname = "ant-purifier-legacy-plugin";
  version = "0.1.0-legacy-basic-${builtins.substring 0 12 sourceHash}";
  src = builtins.path {
    path = ../../java-legacy;
    name = "ant-legacy-java-source";
  };
  nativeBuildInputs = [
    legacySdk.sdk
    jdk21_headless
  ];
  buildPhase = ''
    mkdir -p classes
    ${lib.escapeShellArg "${legacySdk.home}/bin/javac"} -source 1.6 -target 1.6 -encoding UTF-8 \
      -cp ${lib.escapeShellArg "${legacySdk.antJar}:${legacySdk.ivyJar}"} \
      -d classes org/nixpurifiers/ant/legacy/*.java
  '';
  installPhase = ''
    mkdir -p "$out/share/java"
    ${jdk21_headless}/bin/jar --create --file "$out/share/java/ant-purifier-legacy.jar" \
      --date=1980-01-01T00:00:02Z -C classes .
  '';
  meta = {
    description = "Explicit legacy basic Ant/Ivy listener for a source-owned Java SDK";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
  };
}
