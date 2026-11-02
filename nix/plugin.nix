# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  jdk,
  ant,
  apacheIvy,
  version ? null,
}:
let
  sourceHash = builtins.hashString "sha256" (
    builtins.toJSON {
      sources = map (name: builtins.readFile (../java/org/nixpurifiers/ant + "/${name}")) [
        "Activate.java"
        "LockedListener.java"
        "Resolve.java"
        "AntResolve.java"
        "ProjectInputs.java"
        "antlib.xml"
      ];
      toolchain = map toString [
        jdk
        ant
        apacheIvy
      ];
    }
  );
  pluginVersion =
    if version == null then "0.1.0-nix-${builtins.substring 0 12 sourceHash}" else version;
in
stdenvNoCC.mkDerivation {
  pname = "ant-purifier-plugin";
  version = pluginVersion;
  src = ../java;
  nativeBuildInputs = [ jdk ];
  buildPhase = ''
    mkdir -p classes
    javac --release 11 -encoding UTF-8 -cp ${ant}/share/ant/lib/ant.jar:${apacheIvy} \
      -d classes org/nixpurifiers/ant/*.java
    cp org/nixpurifiers/ant/antlib.xml classes/org/nixpurifiers/ant/
  '';
  installPhase = ''
    mkdir -p "$out/share/java"
    jar --create --file "$out/share/java/ant-purifier.jar" \
      --date=1980-01-01T00:00:02Z -C classes .
  '';
  meta = {
    description = "Native Ant integration for Nix-resolved Ivy dependencies";
    homepage = "https://nix-purifiers.github.io/";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
  };
}
