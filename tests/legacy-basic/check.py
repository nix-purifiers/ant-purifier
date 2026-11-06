#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Source-bound exact legacy tuple, native controls, and pure reproducibility."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--namespace-tools', required=True)
p.add_argument('--ip', required=True)
p.add_argument('--foreign-sdk', type=Path)
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
stages = []


def run(name, command):
    with (out/(name+'.log')).open('w') as log:
        result = subprocess.run(list(map(str, command)), cwd=root, stdout=log,
                                stderr=subprocess.STDOUT, timeout=3600)
    stages.append(dict(name=name, exitCode=result.returncode))
    (out/'stages.json').write_text(json.dumps(stages, indent=2)+'\n')
    assert result.returncode == 0, (name, (out/(name+'.log')).read_text()[-10000:])
    print(name, 'passed', flush=True)
    return (out/(name+'.log')).read_text()


archive = json.loads(subprocess.check_output(['nix', 'flake', 'archive', '--json', str(root)], text=True))
source = archive['path']
nar = subprocess.check_output(['nix', 'hash', 'path', source], text=True).strip()
prefix = '''let
 f = builtins.getFlake %s;
 p = import f.inputs.nixpkgs {system="x86_64-linux"; overlays=[f.overlays.default];};
 t = import (f.outPath + "/tests/legacy-basic/toolchains.nix") {pkgs=p; sdkContract=f.inputs.jvmSdkContract;};
in ''' % json.dumps('path:'+source+'?narHash='+nar)
tools = out/'toolchains.nix'
tools.write_text(prefix+'{ cli=t.scope.cli; foreignSdk=t.foreignSdk; }\n')
cli = Path(run('cli-build', ['nix', 'build', '--no-link', '--print-out-paths', '--file', tools, 'cli']).strip().splitlines()[-1])/'bin/ant-purifier'
foreign = a.foreign_sdk or Path(run('foreign-sdk-build', ['nix', 'build', '--no-link', '--print-out-paths', '--file', tools, 'foreignSdk']).strip().splitlines()[-1])
python = [sys.executable, '-B']
scripts = root/'tests/legacy-basic'
run('unlocked', [*python, scripts/'unlocked.py', '--cli', cli, '--output', out/'unlocked'])
run('lifecycle', [*python, scripts/'lifecycle.py', '--cli', cli, '--output', out/'lifecycle',
                  '--namespace-tools', a.namespace_tools, '--ip', a.ip])
run('negative', [*python, scripts/'negative.py', '--cli', cli, '--project', out/'lifecycle/relocated',
                 '--output', out/'negative', '--foreign-sdk', foreign])
run('roles', [*python, scripts/'roles.py', '--cli', cli, '--output', out/'roles', '--foreign-sdk', foreign])
run('containers', [*python, scripts/'containers.py', '--cli', cli, '--output', out/'containers'])
run('update', [*python, scripts/'update.py', '--cli', cli, '--output', out/'update'])
project = subprocess.check_output(['nix', 'store', 'add-path', str(out/'lifecycle/relocated')], text=True).strip()
builder = out/'builder.nix'
builder.write_text(prefix+'t.scope.buildAntProject { src = '+project+'; }\n')
command = ['nix', 'build', '--option', 'allow-import-from-derivation', 'false', '--no-link', '--file', builder, 'tests', 'release']
run('pure-build', command)
run('rebuild', [*command, '--rebuild'])
negative_results = []
for name, arguments, attribute in [
    ('publication', 'publishTarget = "publish";', 'tests.drvPath'),
    ('composition', 'projectDependencies = [ {} ];', 'tests.drvPath'),
    ('projection', '', 'projections'),
]:
    expression = prefix+'(t.scope.buildAntProject { src = '+project+'; '+arguments+' }).'+attribute
    result = subprocess.run(['nix', 'eval', '--option', 'allow-import-from-derivation', 'false',
                             '--raw', '--expr', expression], capture_output=True, text=True)
    (out/('unsupported-'+name+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode != 0 and 'ant-purifier:' in result.stderr
    negative_results.append(dict(name=name, rejectedDuringPureEvaluation=True))
packaging = out/'unsupported-packaging.nix'
packaging.write_text(prefix+'t.scope.buildAntProject { src = '+project+'; buildTargets = [ "unsupported-package" ]; }')
result = subprocess.run(['nix', 'build', '--option', 'allow-import-from-derivation', 'false', '--no-link',
                         '-L', '--file', str(packaging), 'tests'], capture_output=True, text=True)
log = result.stdout+result.stderr
(out/'unsupported-packaging.log').write_text(log)
assert result.returncode != 0 and 'does not support packaging or publication tasks' in log
assert 'compile:' not in log and 'retrieve:' not in log and '[javac]' not in log
negative_results.append(dict(name='packaging', rejectedBeforeDependencyAndCompilerActions=True))
(out/'unsupported-result.json').write_text(json.dumps(negative_results, indent=2)+'\n')
files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.parts}
(out/'result.json').write_text(json.dumps(dict(status='passed', source=source, narHash=nar,
    sourceFiles=files, stages=stages, tuple=dict(ant='1.5.4', ivy='2.4.0', java='1.6.0-119', system='x86_64-linux'),
    scope='basic dependency/compile/Java execution/class tree only'), indent=2)+'\n')
