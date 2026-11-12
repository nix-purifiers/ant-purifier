# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  nix,
  ant,
  jdk,
  apacheIvy,
  plugin,
  jdt-language-server,
  gh,
  cacert,
  nixpkgsSrc,
  purifierSrc,
}:
stdenvNoCC.mkDerivation {
  pname = "ant-purifier";
  version = "0.1.0";
  src = ../..;
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  passthru.purifierRuntime = {
    javaHome = jdk.home;
    ant = "${ant}/bin/ant";
    ivy = toString apacheIvy;
    plugin = "${plugin}/share/java/ant-purifier.jar";
  };
  installPhase = ''
    mkdir -p "$out/bin" "$out/lib/ant-purifier"
    cp -r ant_purifier lib-overlays pkgs "$out/lib/ant-purifier/"
    install -m755 bin/ant-purifier "$out/bin/ant-purifier"
    substituteInPlace "$out/lib/ant-purifier/pkgs/cli/realize.nix" \
      --replace-fail '@nixpkgs@' '${nixpkgsSrc}' \
      --replace-fail '@purifier@' '${purifierSrc}' \
      --replace-fail '@plugin@' '${plugin}' \
      --replace-fail '@ivy@' '${apacheIvy}' \
      --replace-fail '@runtime@' "$out"
    wrapProgram "$out/bin/ant-purifier" \
      --prefix PATH : ${
        lib.makeBinPath [
          python3
          nix
          ant
          gh
        ]
      }:${jdk.home}/bin \
      --prefix PYTHONPATH : "$out/lib/ant-purifier" \
      --set JAVA_HOME ${jdk.home} \
      --set ANT_PURIFIER_COMMAND "$out/bin/ant-purifier" \
      --set ANT_PURIFIER_ANT ${ant}/bin/ant \
      --set ANT_PURIFIER_JAVA ${jdk.home}/bin/java \
      --set ANT_PURIFIER_ANT_HOME ${ant}/share/ant \
      --set ANT_PURIFIER_ANT_VERSION ${ant.version} \
      --set ANT_PURIFIER_IVY_VERSION ${apacheIvy.version} \
      --set ANT_PURIFIER_JAVA_VERSION ${jdk.version} \
      --set ANT_PURIFIER_RESOLVER_VERSION ${plugin.version} \
      --set ANT_PURIFIER_PLUGIN ${plugin}/share/java/ant-purifier.jar \
      --set ANT_PURIFIER_JDTLS ${jdt-language-server}/bin/jdtls \
      --set ANT_PURIFIER_IVY_JAR ${apacheIvy} \
      --set ANT_PURIFIER_INPUT_TOOLS '${purifierSrc}/tools' \
      --set ANT_PURIFIER_LOCK_CLASSPATH '${plugin}/share/java/ant-purifier.jar:${apacheIvy}:${ant}/share/ant/lib/*' \
      --set ANT_PURIFIER_REALIZE "$out/lib/ant-purifier/pkgs/cli/realize.nix" \
      --set-default SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt
    makeWrapper "$out/bin/ant-purifier" "$out/bin/ant" --add-flags 'native --'
    makeWrapper "$out/bin/ant-purifier" "$out/bin/jdtls" --add-flags 'editor --'
  '';
  meta = {
    description = "Locked, Nix-resolved dependencies for Ant and Apache Ivy";
    homepage = "https://nix-purifiers.github.io/";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "ant-purifier";
  };
}
