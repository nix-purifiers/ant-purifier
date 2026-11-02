# SPDX-License-Identifier: MIT
{ pkgs, project }:
pkgs.runCommand "ant-publication-native-consumer"
  {
    nativeBuildInputs = [
      pkgs.ant
      pkgs.jdk
      pkgs.python3
    ];
  }
  ''
      export HOME="$TMPDIR/home"
      export JAVA_HOME=${pkgs.jdk.home}
      export ANT_OPTS="-Djava.io.tmpdir=$TMPDIR"
      mkdir -p "$HOME" "$TMPDIR/consumer"
      cp -r ${./consumer}/. "$TMPDIR/consumer/"
      chmod -R u+w "$TMPDIR/consumer"
      cd "$TMPDIR/consumer"
      python3 - ${project.projections.maven.catalog} ${project.projections.maven} <<'PY'
    import json,sys,xml.etree.ElementTree as ET
    from pathlib import Path
    catalog=json.loads(Path(sys.argv[1]).read_text())
    module=next(m for m in catalog['modules'] if m['group']=='example' and m['name']=='locked-ant')
    root=ET.Element('ivy-module',{'version':'2.0'})
    ET.SubElement(root,'info',{'organisation':'example','module':'consumer','revision':'1.0'})
    deps=ET.SubElement(root,'dependencies')
    ET.SubElement(deps,'dependency',{'org':module['group'],'name':module['name'],'rev':module['version'],'conf':'default->default'})
    ET.ElementTree(root).write('ivy.xml',encoding='unicode')
    settings=ET.Element('ivysettings')
    ET.SubElement(settings,'settings',{'defaultResolver':'projection'})
    ET.SubElement(settings,'caches',{'defaultCacheDir':str(Path.cwd()/'cache'),'useOrigin':'true'})
    resolvers=ET.SubElement(settings,'resolvers')
    ET.SubElement(resolvers,'ibiblio',{'name':'projection','m2compatible':'true','root':Path(sys.argv[2]).as_uri()+'/'})
    ET.ElementTree(settings).write('ivysettings.xml',encoding='unicode')
    PY
      ant -lib ${pkgs.ant-purifier.apacheIvy} test
      touch "$out"
  ''
