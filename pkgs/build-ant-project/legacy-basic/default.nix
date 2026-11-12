# SPDX-License-Identifier: MIT
{
  lib,
  runCommand,
  fetchurl,
  writeText,
  ant,
  legacySdk,
  legacyRuntime,
  python3,
  gnutar,
  gzip,
  purifier,
  stdenv,
}:
{
  src,
  lockFile ? src + "/ant-purifier.lock.json",
  ivyLock ? src + "/ivy.lock.xml",
  ivyFile ? src + "/ivy.xml",
  buildFile ? src + "/build.xml",
  fetchers ? { },
  buildTargets ? [ "test" ],
  publishTarget ? null,
  antProperties ? { },
  nativeBuildInputs ? [ ],
  projectDependencies ? [ ],
  srcFilter ?
    path: type:
    !(builtins.elem (baseNameOf path) [
      ".git"
      ".ant-purifier"
      "build"
      "target"
      "result"
      "__pycache__"
    ]),
}:
let
  lock = purifier.checkLock (
    (import ../../../lib-overlays/default/legacy-basic/read-lock.nix { inherit lib; }) {
      inherit
        src
        lockFile
        ivyLock
        ivyFile
        buildFile
        ;
    }
  );
  expectedProperties = map (name: {
    inherit name;
    hash = builtins.hashString "sha256" (toString antProperties.${name});
  }) (builtins.attrNames antProperties);
  source = lib.cleanSourceWith {
    inherit src;
    filter = srcFilter;
  };
  environment =
    (import ../environment.nix {
      inherit
        runCommand
        fetchurl
        writeText
        purifier
        python3
        stdenv
        ;
    })
      {
        inherit lock fetchers;
        projectDependencies = [ ];
      };
  escape =
    lib.replaceStrings
      [
        "\\"
        "\n"
        "\r"
        "\t"
        "="
        ":"
        "#"
        "!"
        " "
      ]
      [
        "\\\\"
        "\\n"
        "\\r"
        "\\t"
        "\\="
        "\\:"
        "\\#"
        "\\!"
        "\\ "
      ];
  observation = writeText "ant-legacy-captured.properties" (
    lib.concatMapStrings (key: "${escape key}=${escape lock.legacyObserved.${key}}\n") (
      builtins.attrNames lock.legacyObserved
    )
  );
  unsupported = throw "ant-purifier: legacy-basic-v1 exposes a source/class tree; packaging, publication and projections are unsupported";
  project =
    runCommand "purified-ant-legacy-class-tree"
      {
        nativeBuildInputs = [
          ant
          legacySdk.sdk
        ]
        ++ nativeBuildInputs;
        passthru = {
          nativeProfile = "legacy-basic-v1";
          projections = unsupported;
        };
      }
      ''
        export JAVA_HOME=${lib.escapeShellArg legacySdk.home}
        export JAVACMD=${lib.escapeShellArg legacySdk.manager.executable}
        export ANT_HOME=${lib.escapeShellArg "${ant}/share/ant"}
        export ANT_OPTS="-Djava.io.tmpdir=$TMPDIR -Duser.home=$TMPDIR/native-user-home"
        mkdir -p "$TMPDIR/native-user-home" "$out/project"
        cp -r ${source}/. "$out/project/"
        chmod -R u+w "$out/project"
        cd "$out/project"
        cp ${ivyLock} ivy.lock.xml
        cp ${lockFile} ant-purifier.lock.json
        export ANT_PURIFIER_ENVIRONMENT=${environment}
        export ANT_PURIFIER_PROJECT_ROOT="$PWD"
        export ANT_PURIFIER_IVY_FILE="$PWD"/${lib.escapeShellArg lock.ivyFile}
        export ANT_PURIFIER_LEGACY_PROPERTIES=${legacyRuntime.propertiesFile}
        export ANT_PURIFIER_LEGACY_CAPTURED=${observation}
        export ANT_PURIFIER_LEGACY_TARGETS=${lib.escapeShellArg (lib.concatStringsSep "\n" buildTargets)}
        export CLASSPATH=${lib.escapeShellArg "${legacyRuntime.collectorJar}:${legacySdk.ivyJar}:${ant}/share/ant/lib/*:${legacySdk.home}/lib/tools.jar"}
        ${ant}/bin/ant -listener org.nixpurifiers.ant.legacy.NativeReplay \
          -f ${lib.escapeShellArg lock.buildFile} \
          ${
            lib.concatMapStringsSep " " (
              name: lib.escapeShellArg "-D${name}=${toString antProperties.${name}}"
            ) (builtins.attrNames antProperties)
          } \
          ${lib.escapeShellArgs buildTargets}
      '';
  release =
    runCommand "ant-legacy-source-class-tree"
      {
        nativeBuildInputs = [
          gnutar
          gzip
        ];
        passthru = {
          kind = "source-class-tree";
        };
      }
      ''
        mkdir -p "$out"
        tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner \
          -C ${project} -cf - project | gzip -n > "$out/project.tar.gz"
      '';
in
assert publishTarget == null || unsupported;
assert
  projectDependencies == [ ]
  || throw "ant-purifier: project composition is unsupported in legacy-basic-v1";
assert
  buildTargets != [ ]
  && lib.all (
    name: builtins.isString name && builtins.match "[A-Za-z0-9_.:-]+" name != null
  ) buildTargets
  || throw "ant-purifier: legacy buildTargets must be explicit native target names";
assert
  lock.legacyRuntimeContext == legacyRuntime.context
  || throw "ant-purifier: source-owned legacy SDK or native runtime changed; run lock explicitly";
assert
  lock.legacyProperties == expectedProperties
  || throw "ant-purifier: native properties differ from captured legacy configuration";
{
  packages = {
    inherit project environment;
    default = project;
  };
  tests = project;
  fetches = environment;
  inherit release;
  projections = unsupported;
}
