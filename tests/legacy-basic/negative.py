#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject invalid legacy inputs before compiler or project test actions."""
import argparse
import glob
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--cli', type=Path, required=True)
p.add_argument('--project', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--foreign-sdk', type=Path)
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
results = []


def case(name, edit, arguments, expected, extra=None):
    root = out/name
    shutil.copytree(a.project, root, ignore=shutil.ignore_patterns('build', '.ant-purifier', 'test-started'))
    edit(root)
    env = dict(os.environ, XDG_CACHE_HOME=str(out/'cache'))
    for key in ['JAVACMD', 'ANT_OPTS', 'ANT_ARGS']:
        env.pop(key, None)
    env.update(extra or {})
    result = subprocess.run([str(a.cli), *arguments], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    (out/(name+'.log')).write_text(result.stdout)
    assert result.returncode != 0 and expected in result.stdout, (name, result.stdout)
    assert not (root/'build/classes').exists() and not (root/'test-started').exists()
    assert not (root/'package-started.jar').exists()
    results.append(dict(name=name, exitCode=result.returncode, diagnostic=expected,
                        compilerNotStarted=True, projectTestNotStarted=True))
    (out/'result.json').write_text(json.dumps(results, indent=2)+'\n')
    print(name, 'passed', flush=True)


def unchanged(root):
    pass


def change(name, text):
    return lambda root: (root/name).write_text((root/name).read_text()+text)


def json_edit(edit):
    def apply(root):
        file = root/'ant-purifier.lock.json'
        value = json.loads(file.read_text())
        edit(value)
        value['contentHash'] = hashlib.sha256(json.dumps(
            {k: v for k, v in value.items() if k != 'contentHash'},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        file.write_text(json.dumps(value))
    return apply


case('packaging-before-dependencies', unchanged, ['native', '--', 'unsupported-package'],
     'does not support packaging or publication tasks')
case('xml-source-changed', change('ivy.xml', '\n'), ['native', '--', 'test'], 'changed')
case('build-source-changed', change('build.xml', '\n'), ['native', '--', 'test'], 'changed')
case('payload-changed', change('ant-purifier.lock.json.payload.json', '\n'),
     ['native', '--', 'test'], 'payload')
case('unknown-outer-field', json_edit(lambda v: v.update(unexpected=True)),
     ['native', '--', 'test'], 'invalid closed legacy companion')
case('context-hash-changed', json_edit(lambda v: v.update(runtimeHash='0'*64)),
     ['native', '--', 'test'], 'hash')
case('profile-downgrade', json_edit(lambda v: v.update(version=1)),
     ['native', '--', 'test'], 'unsupported legacy profile')

if a.foreign_sdk:
    case('same-version-foreign-manager', unchanged, ['native', '--', 'test'],
         'native JAVACMD differs', dict(JAVACMD=str(a.foreign_sdk/'bin/java')))
    exports = dict(re.findall(r"^export ([A-Z_]+)='([^']*)'", a.cli.read_text(), re.M))
    context = json.loads(Path(exports['ANT_PURIFIER_LEGACY_CONTEXT']).read_text())
    classpath_entries = []
    for entry in exports['ANT_PURIFIER_LOCK_CLASSPATH'].split(':'):
        classpath_entries.extend(sorted(glob.glob(entry)) if '*' in entry else [entry])
    original_classpath = ':'.join(classpath_entries)
    for name, key in [('ant', 'ant'), ('ivy', 'ivy'), ('collector', 'collector')]:
        original = context[key].get('jar', context[key]['output'])
        copied = out/(name+'-same-bytes.jar')
        shutil.copyfile(original, copied)
        assert original in classpath_entries
        classpath = original_classpath.replace(original, str(copied))
        command = [context['manager']['executable'], '-cp', classpath,
                   'org.nixpurifiers.ant.legacy.Check']
        env = dict(os.environ, ANT_PURIFIER_LEGACY_PROPERTIES=exports['ANT_PURIFIER_LEGACY_PROPERTIES'])
        run = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, timeout=60)
        log = run.stdout+run.stderr
        (out/('foreign-'+name+'-origin.log')).write_text(log)
        assert run.returncode != 0 and ('actual '+name+'.jar differs') in log, log
        results.append(dict(name='same-bytes-foreign-'+name+'-origin', exitCode=run.returncode,
                            projectActionsNotInvoked=True))
    command = [str(a.foreign_sdk/'bin/java'), '-cp', exports['ANT_PURIFIER_LOCK_CLASSPATH'],
               'org.nixpurifiers.ant.legacy.Check']
    run = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, timeout=60)
    log = run.stdout+run.stderr
    (out/'foreign-sdk-process.log').write_text(log)
    assert run.returncode != 0 and 'actual legacy manager executable differs' in log, log
    results.append(dict(name='same-version-foreign-native-process', exitCode=run.returncode,
                        projectActionsNotInvoked=True))
    (out/'result.json').write_text(json.dumps(results, indent=2)+'\n')
