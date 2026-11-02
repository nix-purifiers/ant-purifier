# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/ant-purifier.lock.json",
  ivyLock ? src + "/ivy.lock.xml",
  ivyFile ? src + "/ivy.xml",
  buildFile ? src + "/build.xml",
}:
let
  problem = message: "ant-purifier: ${message}; run ant-purifier lock";
  exists = builtins.all builtins.pathExists [
    lockFile
    ivyLock
    ivyFile
    buildFile
  ];
  data =
    if exists then
      builtins.addErrorContext (problem "cannot parse companion lock") (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
  native = if exists then builtins.readFile ivyLock else "";
  nameRe = "[A-Za-z0-9][A-Za-z0-9_.+-]*";
  nameOK = v: builtins.isString v && builtins.match nameRe v != null;
  urlOK = v: builtins.isString v && builtins.match "https?://[^/@[:space:]]+/[^[:space:]]*" v != null;
  hashOK = v: builtins.isString v && builtins.match "sha256-[A-Za-z0-9+/]{43}=" v != null;
  key = m: "${m.group}:${m.name}";
  coordinate = m: "${builtins.replaceStrings [ "." ] [ "/" ] m.group}/${m.name}/${m.version}";
  pinPieces = builtins.split "<override[[:space:]]+([^>]+)/>" native;
  attribute =
    name: tag:
    let
      found = builtins.match (".*[[:space:]]" + name + ''="([^"]*)".*'') (" " + tag);
    in
    if found == null then null else builtins.head found;
  pinTags = map builtins.head (builtins.filter builtins.isList pinPieces);
  pins = builtins.listToAttrs (
    map
      (tag: {
        name = "${attribute "org" tag}:${attribute "module" tag}";
        value = attribute "rev" tag;
      })
      (
        builtins.filter (
          tag:
          attribute "matcher" tag == "exact"
          && builtins.all (name: nameOK (attribute name tag)) [
            "org"
            "module"
            "rev"
          ]
        ) pinTags
      )
  );
  ignored = [
    ".git"
    ".ant-purifier"
    "build"
    "target"
    "result"
    "__pycache__"
    "node_modules"
  ];
  walk =
    prefix: directory:
    lib.concatMap (
      name:
      let
        kind = (builtins.readDir directory).${name};
        path = directory + "/${name}";
        relative = prefix + name;
      in
      if
        builtins.elem name ignored || toString path == toString ivyLock || relative == "ivy.lock.xml"
      then
        [ ]
      else if kind == "directory" then
        walk "${relative}/" path
      else
        lib.optional (lib.hasSuffix ".xml" name || lib.hasSuffix ".properties" name) {
          name = relative;
          value = builtins.hashFile "sha256" path;
        }
    ) (builtins.attrNames (builtins.readDir directory));
  inputs = builtins.listToAttrs (walk "" src);
  modules = data.modules or [ ];
  artifacts = data.artifacts or [ ];
  roots = data.sourceRoots or null;
  metadata = data.metadata or [ ];
  metadataOK =
    m:
    builtins.isAttrs m
    && builtins.all (name: nameOK (m.${name} or null)) [
      "group"
      "name"
      "version"
    ]
    && urlOK (m.url or null)
    && hashOK (m.hash or null);
  moduleOK =
    m:
    builtins.isAttrs m
    && builtins.all (n: nameOK (m.${n} or null)) [
      "group"
      "name"
      "version"
    ]
    && (pins.${key m} or null) == m.version
    && builtins.isString (m.descriptor or null)
    && lib.hasInfix "<ivy-module" m.descriptor
    && (
      !(m ? original)
      || (
        builtins.isAttrs m.original && urlOK (m.original.url or null) && hashOK (m.original.hash or null)
      )
    );
  artifactOK =
    a:
    builtins.isAttrs a
    && builtins.all (n: nameOK (a.${n} or null)) [
      "group"
      "module"
      "version"
      "name"
      "ext"
      "type"
    ]
    && builtins.isString (a.classifier or null)
    && (a.classifier == "" || nameOK a.classifier)
    && builtins.elem "${a.group}:${a.module}" (map key modules)
    && (pins."${a.group}:${a.module}" or null) == a.version
    &&
      (a.path or null) == "${
        builtins.replaceStrings [ "." ] [ "/" ] a.group
      }/${a.module}/${a.version}/${a.name}-${a.version}${
        lib.optionalString (a.classifier != "") "-${a.classifier}"
      }.${a.ext}"
    && urlOK (a.url or null)
    && hashOK (a.hash or null);
  problems = map problem (
    if !exists then
      [ "missing Ant/Ivy configuration or lockfiles" ]
    else if !builtins.isAttrs data || (data.version or null) != 1 then
      [ "unsupported companion format" ]
    else if
      (data.contentHash or null)
      != builtins.hashString "sha256" (builtins.toJSON (removeAttrs data [ "contentHash" ]))
    then
      [ "contentHash mismatch" ]
    else if
      (data.nativeHash or null) != builtins.hashFile "sha256" ivyLock || (data.inputs or null) != inputs
    then
      [ "configuration or native lock changed" ]
    else if
      (data.ivyHash or null) != builtins.hashFile "sha256" ivyFile
      || (data.buildHash or null) != builtins.hashFile "sha256" buildFile
    then
      [ "Ivy or Ant configuration changed" ]
    else if
      !builtins.isList roots
      || !builtins.all (
        p:
        builtins.isString p
        && p != ""
        && !(lib.hasPrefix "/" p)
        && !(builtins.elem ".." (lib.splitString "/" p))
      ) roots
    then
      [ "missing or invalid native source directories" ]
    else if !builtins.isList metadata || !builtins.all metadataOK metadata then
      [ "missing or invalid native POM metadata closure" ]
    else if !builtins.isList modules || !builtins.isList artifacts then
      [ "invalid native dependency graph" ]
    else if !builtins.all moduleOK modules then
      [ "native pins or module metadata do not match" ]
    else if builtins.length (lib.unique (map key modules)) != builtins.length modules then
      [ "duplicate selected module" ]
    else if !builtins.all artifactOK artifacts then
      [ "invalid native artifact metadata" ]
    else if builtins.length (lib.unique (map (a: a.path) artifacts)) != builtins.length artifacts then
      [ "ambiguous artifact path" ]
    else if
      !builtins.all (name: builtins.isString (data.${name} or null)) [
        "antVersion"
        "ivyVersion"
        "javaVersion"
        "resolveTarget"
        "ivyFile"
        "buildFile"
      ]
    then
      [ "missing native toolchain or target metadata" ]
    else
      [ ]
  );
  usable = problems == [ ];
in
{
  purifier = "ant-purifier";
  inherit problems;
  outputs.repository = { };
  antVersion = data.antVersion or "";
  ivyVersion = data.ivyVersion or "";
  javaVersion = data.javaVersion or "";
  resolveTarget = data.resolveTarget or "";
  ivyFile = data.ivyFile or "";
  buildFile = data.buildFile or "";
  modules = if usable then modules else [ ];
  artifacts = if usable then artifacts else [ ];
  sourceRoots = data.sourceRoots or [ ];
  mavenRuntimeComplete =
    usable
    && builtins.all (m: builtins.any (p: key p == key m && p.version == m.version) metadata) modules;
  entries =
    if !usable then
      [ ]
    else
      map (a: {
        path = "repository/${a.path}";
        inherit (a) url hash;
        mirrors = [ ];
      }) artifacts
      ++ map (a: {
        path = "runtime-repository/${a.path}";
        inherit (a) url hash;
        mirrors = [ ];
      }) artifacts
      ++ map (m: {
        path = "runtime-repository/${coordinate m}/${m.name}-${m.version}.pom";
        inherit (m) url hash;
        mirrors = [ ];
      }) metadata
      ++ lib.concatMap (
        m:
        [
          {
            path = "repository/${coordinate m}/ivy.xml";
            contents = m.descriptor;
          }
        ]
        ++ lib.optional (m ? original) {
          path = "origins/${coordinate m}/original";
          inherit (m.original) url hash;
          mirrors = [ ];
        }
      ) modules
      ++ [
        {
          path = "repository/purifier-runtime-modules.json";
          contents = builtins.toJSON { modules = map (m: { inherit (m) group name version; }) modules; };
        }
        {
          path = "ivy.lock.xml";
          contents = native;
        }
        {
          path = "runtime-repository/purifier-runtime-modules.json";
          contents = builtins.toJSON { modules = map (m: { inherit (m) group name version; }) modules; };
        }
      ];
}
