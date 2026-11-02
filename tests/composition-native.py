#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Native Ant locking, execution, editors, and pure publication of a Nix input."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parent.parent
system = subprocess.check_output(['nix', 'eval', '--impure', '--raw', '--expr',
                                  'builtins.currentSystem'], text=True).strip()
snapshot = json.loads(subprocess.check_output(['nix', 'flake', 'metadata', '--json',
    '--no-write-lock-file', 'path:' + str(root)], text=True))['path']
with tempfile.TemporaryDirectory(prefix='ant-native-composition-') as temporary:
    temporary = Path(temporary)
    subprocess.run(['nix-store', '--add-root', str(temporary / 'source'), '--realise', snapshot], check=True)
    package = subprocess.check_output(['nix', 'build', str(root) + '#default', '--print-out-paths',
        '--out-link', str(temporary / 'cli')], text=True).strip().splitlines()[-1]
    cli = Path(package) / 'bin/ant-purifier'
    for transitive in (False, True):
        project = temporary / ('transitive' if transitive else 'direct')
        shutil.copytree(root / 'examples/minimal', project)
        for name in ['ant-purifier.lock.json', 'ivy.lock.xml']:
            (project / name).unlink(missing_ok=True)
        (project / 'build.properties').write_text('commons.version=99.0\n')
        if transitive:
            descriptor = project / 'ivy.xml'
            descriptor.write_text(descriptor.read_text().replace('name="commons-lang3"', 'name="commons-text"')
                .replace('rev="${commons.version}"', 'rev="1.13.0"'))
            (project / 'src/Main.java').write_text('''import org.apache.commons.text.WordUtils;
    public final class Main { public static void main(String[] args) {
        String result = WordUtils.capitalizeFully("hello nix");
        if (!result.equals("Hello Nix")) throw new AssertionError(result);
        System.out.println(result);
    } }
    ''')
        declaration = (project / 'ivy.xml').read_bytes()
        reference = 'path:' + snapshot + '#checks.' + system + '.composition-provider'
        def run(*arguments):
            subprocess.run([str(value) for value in arguments], cwd=project, check=True)
        run(cli, 'lock', '--input', reference)
        data = json.loads((project / 'ant-purifier.lock.json').read_text())
        assert len(data['projectInputs']) == 1
        assert {(m['group'], m['name']) for m in data['modules']} == ({('org.apache.commons', 'commons-text')} if transitive else set())
        assert not any(a['module'] == 'commons-lang3' for a in data['artifacts'])
        assert not any(node.get('module') == 'commons-lang3' for node in ET.parse(project / 'ivy.lock.xml').findall('./dependencies/override'))
        run(cli, 'prefetch')
        run(cli.parent / 'ant', 'test')
        assert (project / 'ivy.xml').read_bytes() == declaration
        expression = '''let
          f = builtins.getFlake ("path:" + builtins.getEnv "ANT_COMPOSITION_FLAKE");
          p = import f.inputs.nixpkgs {system=builtins.currentSystem;overlays=[f.overlays.default];};
          b = p.ant-purifier.buildAntProject {
            src = /. + builtins.getEnv "ANT_COMPOSITION_PROJECT";
            publishTarget = "publish";
          };
        in b.projections.maven'''
        repository = Path(subprocess.check_output(['nix', 'build', '--impure', '--no-link',
            '--print-out-paths', '--print-build-logs', '--expr', expression], text=True,
            env=dict(os.environ, ANT_COMPOSITION_FLAKE=str(root), ANT_COMPOSITION_PROJECT=str(project))).strip())
        pom = next((repository / 'example/locked-ant').glob('*/*.pom'))
        assert '-nix-' in pom.parent.name
        dependency = ET.parse(pom).find('.//{*}dependency')
        version = dependency.findtext('{*}version')
        assert '-nix-' in version
        assert next((repository / 'org/apache/commons/commons-lang3').glob('*/*-nix-*.jar')).is_file()
        print('ANT NATIVE AND SANDBOX INPUT COMPOSITION PASSED')
