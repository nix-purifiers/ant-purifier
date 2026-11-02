# SPDX-License-Identifier: MIT
{ pkgs, project }:
pkgs.runCommand "ant-editor-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  export HOME="$TMPDIR/home"
  export JAVA_HOME=${pkgs.jdk.home}
  export ANT_PURIFIER_JDTLS=${pkgs.jdt-language-server}/bin/jdtls
  export PYTHONPATH=${../.}
  mkdir -p "$HOME" "$TMPDIR/project"
  cp -r ${../examples/minimal}/. "$TMPDIR/project/"
  chmod -R u+w "$TMPDIR/project"
  cd "$TMPDIR/project"
  python3 ${./editor.py} ${project.packages.environment}
  touch "$out"
''
