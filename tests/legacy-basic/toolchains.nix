# SPDX-License-Identifier: MIT
# Explicit caller-owned test inputs; production does not select an SDK by major.
{ pkgs, sdkContract }:
assert pkgs.stdenv.hostPlatform.system == "x86_64-linux";
let
  sdk = pkgs.stdenv.mkDerivation {
    pname = "ant-legacy-zulu-jdk";
    version = "6.0.119";
    src = pkgs.fetchurl {
      url = "https://cdn.azul.com/zulu/bin/zulu6.22.0.3-ca-jdk6.0.119-linux_x64.tar.gz";
      hash = "sha256-3UdltF2fH8MZpuW+C7x5NxWC2qj9d4ctUQcvFt7KJiU=";
    };
    nativeBuildInputs = [ pkgs.autoPatchelfHook ];
    buildInputs = [
      pkgs.stdenv.cc.cc.lib
      pkgs.zlib
    ];
    # These headless tests establish no AWT/audio/GUI compatibility.
    autoPatchelfIgnoreMissingDeps = true;
    installPhase = ''mkdir -p "$out"; cp -a . "$out/"'';
    dontStrip = true;
  };
  ant = pkgs.stdenvNoCC.mkDerivation {
    pname = "ant-legacy";
    version = "1.5.4";
    src = pkgs.fetchurl {
      url = "https://archive.apache.org/dist/ant/binaries/apache-ant-1.5.4-bin.zip";
      hash = "sha256-cQAwDOc12KQrCzfNhtQPPqPg5GxGRoiT+cp+p2ZEbAs=";
    };
    nativeBuildInputs = [ pkgs.unzip ];
    installPhase = ''
      mkdir -p "$out/share/ant" "$out/bin"
      cp -a . "$out/share/ant/"
      chmod +x "$out/share/ant/bin/ant"
      ln -s "$out/share/ant/bin/ant" "$out/bin/ant"
    '';
  };
  apacheIvy = pkgs.fetchurl {
    url = "https://repo.maven.apache.org/maven2/org/apache/ivy/ivy/2.4.0/ivy-2.4.0.jar";
    hash = "sha256-zoHLI0QGsJO1uN6fb1sqUO0IJNaiNYkTU+jT6UGlOXA=";
    passthru.version = "2.4.0";
  };
  adapter = (import (sdkContract + "/nix/lib/jvm-sdk-adapter.nix") { inherit (pkgs) lib; }) {
    inherit sdk;
    system = pkgs.stdenv.hostPlatform.system;
    home = "${sdk}";
    executable = "${sdk}/bin/java";
    runtimeHome = "${sdk}/jre";
  };
in
{
  inherit
    sdk
    ant
    apacheIvy
    adapter
    ;
  foreignSdk = sdk.overrideAttrs (_: {
    pname = "ant-legacy-foreign-zulu-jdk";
  });
  scope = pkgs.ant-purifier.overrideScope (
    _: _: {
      nativeProfile = "legacy-basic-v1";
      legacyJvmAdapter = adapter;
      inherit ant apacheIvy;
    }
  );
}
