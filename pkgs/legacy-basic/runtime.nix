# SPDX-License-Identifier: MIT
{
  lib,
  writeText,
  legacySdk,
  plugin,
}:
let
  collectorJar = "${plugin}/share/java/ant-purifier-legacy.jar";
  context = legacySdk.context // {
    collector = {
      output = toString plugin;
      outputContext = builtins.getContext (toString plugin);
      jar = collectorJar;
      jarContext = builtins.getContext collectorJar;
      version = plugin.version;
    };
  };
  contextHash = builtins.hashString "sha256" (builtins.toJSON context);
  properties = {
    "profile" = "legacy-basic-v1";
    "context.hash" = contextHash;
    "sdk.output" = context.sdk.output;
    "sdk.home" = context.sdk.home;
    "sdk.identity" = context.sdkIdentityHash;
    "manager.executable" = context.manager.executable;
    "manager.runtimeHome" = context.manager.runtimeHome;
    "manager.identity" = context.managerIdentityHash;
    "compiler.jar" = "${legacySdk.home}/lib/tools.jar";
    "compiler.executable" = "${legacySdk.home}/bin/javac";
    "ant.jar" = context.ant.jar;
    "ant.version" = context.ant.version;
    "ivy.jar" = context.ivy.output;
    "ivy.version" = context.ivy.version;
    "collector.jar" = collectorJar;
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
in
assert
  builtins.all (p: !(lib.hasInfix ":" p)) [
    legacySdk.antJar
    legacySdk.ivyJar
    collectorJar
    properties."compiler.jar"
  ]
  || throw "ant-purifier: legacy native classpath entries cannot contain a colon";
{
  inherit
    context
    contextHash
    properties
    collectorJar
    ;
  contextFile = writeText "ant-legacy-context.json" (builtins.toJSON context);
  propertiesFile = writeText "ant-legacy-context.properties" (
    lib.concatMapStrings (key: "${escape key}=${escape properties.${key}}\n") (
      builtins.attrNames properties
    )
  );
  closureInputs = legacySdk.closureInputs ++ [
    plugin
    collectorJar
  ];
}
