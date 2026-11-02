# SPDX-License-Identifier: MIT
{
  runCommand,
  fetchurl,
  writeText,
  purifier,
  python3,
  stdenv,
}:
{
  lock,
  fetchers ? { },
  projectDependencies ? purifier.lockedProjectInputs {
    inputs = lock.projectInputs or [ ];
    system = stdenv.hostPlatform.system;
  },
}:
let
  checked = purifier.checkLock lock;
  sources = purifier.tree (
    {
      name = "purified-ivy-repository";
      entries = checked.entries;
      inherit runCommand fetchurl;
    }
    // fetchers
  );
  provided = purifier.jvmProjections {
    repository = null;
    dependencies = projectDependencies;
    inherit runCommand python3;
  };
  settings = writeText "purified-ivysettings.xml" ''
    <ivysettings>
      <settings defaultResolver="purified"/>
      <caches defaultCacheDir="@CACHE@" useOrigin="true"/>
      <resolvers>
        <filesystem name="purified" m2compatible="true">
          <ivy pattern="${sources}/repository/[organisation]/[module]/[revision]/ivy.xml"/>
          <artifact pattern="${sources}/repository/[organisation]/[module]/[revision]/[artifact]-[revision](-[classifier]).[ext]"/>
        </filesystem>
        <filesystem name="purifier-publications">
          <ivy pattern="@PUBLICATIONS@/[organisation]/[module]/[revision]/ivys/ivy.xml"/>
          <artifact pattern="@PUBLICATIONS@/[organisation]/[module]/[revision]/[type]s/[artifact](-[classifier]).[ext]"/>
        </filesystem>
      </resolvers>
    </ivysettings>
  '';
  metadata = writeText "ant-editor-metadata.json" (
    builtins.toJSON {
      classpath = map (a: "${sources}/repository/${a.path}") (
        builtins.filter (
          a:
          builtins.elem a.ext [
            "jar"
            "zip"
          ]
          && !(builtins.elem a.type [
            "src"
            "source"
            "sources"
            "doc"
            "javadoc"
          ])
          && !(builtins.elem a.classifier [
            "sources"
            "javadoc"
          ])
        ) checked.artifacts
      );
      inherit (checked) sourceRoots;
      libraries =
        map
          (
            a:
            let
              attachments = builtins.filter (
                s:
                s.group == a.group
                && s.module == a.module
                && s.version == a.version
                && (
                  s.classifier == "sources"
                  || builtins.elem s.type [
                    "src"
                    "source"
                    "sources"
                  ]
                )
              ) checked.artifacts;
            in
            {
              path = "${sources}/repository/${a.path}";
              source =
                if attachments == [ ] then null else "${sources}/repository/${(builtins.head attachments).path}";
            }
          )
          (
            builtins.filter (
              a:
              builtins.elem a.ext [
                "jar"
                "zip"
              ]
              && !(builtins.elem a.type [
                "src"
                "source"
                "sources"
                "doc"
                "javadoc"
              ])
              && !(builtins.elem a.classifier [
                "sources"
                "javadoc"
              ])
            ) checked.artifacts
          );
    }
  );
in
runCommand "purified-ant-environment" { } ''
  mkdir -p "$out"
  ln -s ${sources}/repository "$out/repository"
  ln -s ${sources}/runtime-repository "$out/runtime-repository"
  ${
    if projectDependencies == [ ] then
      ''
        ln -s ${sources}/ivy.lock.xml "$out/ivy.lock.xml"
        ln -s ${settings} "$out/settings.xml"
        ln -s ${metadata} "$out/metadata.json"
      ''
    else
      ''
        cp ${sources}/ivy.lock.xml "$out/ivy.lock.xml"
        cp ${settings} "$out/settings.xml"
        cp ${metadata} "$out/metadata.json"
        chmod u+w "$out/ivy.lock.xml" "$out/settings.xml" "$out/metadata.json"
        ${python3}/bin/python ${../ant_purifier/project_inputs.py} \
          "$out" ${provided.maven} ${provided.maven.catalog}
      ''
  }
''
