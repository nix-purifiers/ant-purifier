# ant-purifier

Locked, Nix-resolved dependencies for Ant and Apache Ivy.

## Quickstart

From a project with `build.xml`, `ivy.xml`, and an Ivy resolution target:

```sh
nix shell 'github:nix-purifiers/ant-purifier'
ant-purifier lock
ant-purifier prefetch
ant test
```

The default resolver target is `resolve`. Select another with
`ant-purifier --resolve-target dependencies lock`.
Commit `ivy.lock.xml` and `ant-purifier.lock.json`.
The native Ivy lock records exact revisions; its companion records artifact
hashes, original metadata, and the project configuration used to resolve them.

The shell provides an `ant` wrapper that selects the locked repository before
running your targets. Without a lockfile it warns and runs ordinary Ant/Ivy.
A stale or invalid lockfile fails with a request to run `ant-purifier lock`.
The wrapper can also be installed through your usual Nix configuration.

```sh
ant-purifier update commons-lang3
ant-purifier update
```

A named update retains the other selected revisions. Running `lock` again
retains existing pins, including when the companion needs regenerating.
Use `--property name=value` for properties needed by your resolver target.

## Native Ant plugin

Projects can activate the plugin from their build instead of requiring the
wrapper. Add its Maven repository to Ivy:

```xml
<ibiblio name="purifier" m2compatible="true"
  root="https://nix-purifiers.github.io/ant-purifier/maven"/>
```

Resolve `io.github.nix-purifiers:ant-purifier` at a published release version
into a separate bootstrap classpath, then activate it before project resolution:

```xml
<taskdef uri="antlib:org.nixpurifiers.ant"
  resource="org/nixpurifiers/ant/antlib.xml"
  classpathref="purifier.bootstrap"/>
<purifier:activate
  xmlns:purifier="antlib:org.nixpurifiers.ant"/>
```

The [release repository](https://nix-purifiers.github.io/ant-purifier/maven/)
contains versioned JARs and POMs. Keep bootstrap dependencies separate from the
application descriptor. Published plugins obtain their matching Nix runtime
automatically. Maven resolution prints a warning that the plugin was resolved
impurely and recommends the wrapper for pure plugin resolution.

## Editor

Configure your Java language client to launch the supplied `jdtls` command.
It prepares Eclipse project metadata with immutable dependency and source JAR
paths, preserving existing IvyDE configuration for restoration when the lock
is removed. JDT's workspace is kept outside the source tree.

`prefetch` roots the dependency repository, compiler, Ant, plugin, and editor
toolchain beside the selected lockfile so subsequent builds and editor sessions
can run offline.

## Dependencies from another purified project

Use a producer package that exports `projections.maven`:

```sh
ant-purifier lock \
  --input 'github:owner/library/<rev>#library'
ant-purifier prefetch
ant test
```

The catalog selects supplied modules automatically, including their immutable
Nix-derived versions. Keep the dependency declarations in `ivy.xml`; no version
rewrite table is needed. Repeat `--input` for additional producers.

The companion lock records pinned Nix sources. Their artifacts and native version
pins stay out of the download locks. Relocking retains the source pins; `update`
refreshes them. Native resolution and editor metadata use the same selected files.

Nix builds read the recorded inputs by default. They can also take
`projectDependencies = [ producer.packages.${system}.library ];`. Publication
views include the supplied closure and rewrite descriptors for downstream tools.

## Nix builds

Apply `overlays.default`, then call the scoped builder:

```nix
pkgs.ant-purifier.buildAntProject {
  src = ./project;
  buildTargets = [ "test" ];
  publishTarget = "publish";
}
```

The result exposes `packages`, `tests`, `release`, and `fetches`.
`packages.project` builds in the sandbox; `packages.environment` is the locked
dependency repository. With `publishTarget`, `packages.repository` contains
the project's native Ivy publications, separate from downloaded dependencies.
`projections.maven` and `projections.ivy` expose shared JVM publication views.
Maven projection requires original Maven POM metadata, including parent and BOM
closure; a graph available only as Ivy metadata fails explicitly.

The builder accepts external `lockFile`, `ivyLock`, `ivyFile`, and `buildFile`
paths and caller-provided `fetchers`. The CLI equivalents are `--lockfile`,
`--native-lock`, `--ivy-file`, and `--build-file`. A new external native lock
starts from the working copy's pins without overwriting its lockfiles.

## Supported scope

Linux x86-64 and ARM64 are checked with Ant 1.10.18, Ivy 2.6.0, and JDK 21.
The native plugin targets Java 11. Dependency sources currently use HTTP(S);
private mirrors can be supplied through builder fetchers.

Inline Ivy resolution, inherited descriptors, branches, multiple project base
directories, custom cache managers, and explicit artifact URLs are rejected.
Arbitrary downloads performed by other Ant tasks need their own locked inputs.

## Credits

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).

## License

MIT. Copyright the nix-purifier developers.
