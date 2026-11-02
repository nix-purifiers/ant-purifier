# SPDX-License-Identifier: MIT
{
  lib,
  runCommand,
  fetchurl,
  writeText,
  ant,
  jdk,
  apacheIvy,
  plugin,
  python3,
  gnutar,
  gzip,
  purifier,
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
    (import ./read-lock.nix { inherit lib; }) {
      inherit
        src
        lockFile
        ivyLock
        ivyFile
        buildFile
        ;
    }
  );
  source = lib.cleanSourceWith {
    inherit src;
    filter = srcFilter;
  };
  environment =
    (import ./environment.nix {
      inherit
        runCommand
        fetchurl
        writeText
        purifier
        ;
    })
      { inherit lock fetchers; };
  build =
    runCommand "purified-ant-project"
      {
        nativeBuildInputs = [
          ant
          jdk
        ]
        ++ nativeBuildInputs;
      }
      ''
            export HOME="$TMPDIR/home"
            export JAVA_HOME=${jdk.home}
            export ANT_OPTS="-Djava.io.tmpdir=$TMPDIR"
            export ANT_PURIFIER_ENVIRONMENT=${environment}
            export ANT_PURIFIER_NIX_DELIVERED=1
            export ANT_PURIFIER_REPRODUCIBLE=1
            mkdir -p "$HOME" "$out/project" "$out/repository"
            cp -r ${source}/. "$out/project/"
            chmod -R u+w "$out/project"
            cd "$out/project"
            mkdir -p "$(dirname ${lib.escapeShellArg lock.ivyFile})" "$(dirname ${lib.escapeShellArg lock.buildFile})"
            cp ${ivyFile} ${lib.escapeShellArg lock.ivyFile}
            cp ${buildFile} ${lib.escapeShellArg lock.buildFile}
            cp ${ivyLock} ivy.lock.xml
            cp ${lockFile} ant-purifier.lock.json
            export ANT_PURIFIER_PROJECT_ROOT="$PWD"
        export ANT_PURIFIER_IVY_FILE="$PWD"/${lib.escapeShellArg lock.ivyFile}
            ${lib.optionalString (
              publishTarget != null
            ) ''export ANT_PURIFIER_PUBLICATION_REPOSITORY="$out/repository"''}
            ant -lib ${plugin}/share/java/ant-purifier.jar -lib ${apacheIvy} \
              -listener org.nixpurifiers.ant.LockedListener \
              -f ${lib.escapeShellArg lock.buildFile} \
              ${
                lib.concatMapStringsSep " " (
                  name: lib.escapeShellArg "-D${name}=${toString antProperties.${name}}"
                ) (builtins.attrNames antProperties)
              } \
              ${lib.escapeShellArgs (buildTargets ++ lib.optional (publishTarget != null) publishTarget)}
      '';
  projections =
    assert
      lock.mavenRuntimeComplete
      || throw "ant-purifier: this native Ivy graph needs an Ivy-to-Maven runtime projection; the native packages.repository remains available";
    purifier.jvmProjections {
      repository = if publishTarget == null then null else "${build}/repository";
      producer = build;
      runtimeRepository = "${environment}/runtime-repository";
      dependencies = projectDependencies;
      formats = [
        "maven"
        "ivy"
      ];
      inherit runCommand python3;
    };
  project = build.overrideAttrs (old: {
    passthru = (old.passthru or { }) // {
      inherit projections;
    };
  });
  release =
    runCommand "ant-project-release"
      {
        nativeBuildInputs = [
          gnutar
          gzip
        ];
      }
      ''
        mkdir -p "$out"
        tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner \
          -C ${project} -cf - project repository | gzip -n > "$out/project.tar.gz"
      '';
in
assert
  projectDependencies == [ ]
  || throw "ant-purifier: consuming Nix-built JVM project inputs is not wired yet; native publication projections are available for other tools";
assert
  lock.antVersion == ant.version
  || throw "ant-purifier: Ant differs from the lock; override the scope's ant or update the lock";
assert
  lock.javaVersion == jdk.version
  || throw "ant-purifier: JDK differs from the lock; override the scope's jdk or update the lock";
{
  packages = {
    inherit project environment;
    default = project;
  }
  // lib.optionalAttrs (publishTarget != null) { repository = "${project}/repository"; };
  tests = project;
  inherit release projections;
  fetches = lock.entries;
}
