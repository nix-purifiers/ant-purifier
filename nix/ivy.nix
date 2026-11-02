# SPDX-License-Identifier: MIT
{ fetchurl }:
fetchurl {
  url = "https://repo.maven.apache.org/maven2/org/apache/ivy/ivy/2.6.0/ivy-2.6.0.jar";
  passthru.version = "2.6.0";
  hash = "sha256-fhT+dzBqjMcRl8s/FoHp5nPMwEJUpe3n6EjiJISR7Hg=";
}
