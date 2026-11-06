#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Measure original Ant/Ivy dynamic revision and explicit update behavior."""
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import xml.etree.ElementTree as ET
import zipfile
import fixture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--cli', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
exports = dict(re.findall(r"^export ([A-Z_]+)='([^']*)'", a.cli.read_text(), re.M))
context = json.loads(Path(exports['ANT_PURIFIER_LEGACY_CONTEXT']).read_text())
fixture.repository(out/'repository', context)
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *unused): pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(out/'repository')))
threading.Thread(target=server.serve_forever, daemon=True).start()
fixture.project(out/'project', 'http://127.0.0.1:'+str(server.server_port), context, revision='latest.integration')
env = dict(os.environ, JAVA_HOME=context['sdk']['home'], ANT_HOME=context['ant']['output']+'/share/ant',
           CLASSPATH=context['ivy']['output'], XDG_CACHE_HOME=str(out/'cache'))
for key in ['JAVACMD', 'ANT_ARGS', 'ANT_OPTS']: env.pop(key, None)
results = []
def run(name, command, extra=None, error=None):
    result = subprocess.run(list(map(str, command)), cwd=out/'project', env=dict(env, **(extra or {})),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    (out/(name+'.log')).write_text(result.stdout)
    assert (result.returncode != 0 and error in result.stdout) if error else result.returncode == 0, result.stdout
    results.append(dict(name=name, exitCode=result.returncode))
    print(name, result.returncode, flush=True)
def selected():
    value = json.loads((out/'project/ant-purifier.lock.json.payload.json').read_text())
    return {m['group']+':'+m['name']: m['version'] for m in value['modules']}
def snapshot(name):
    directory = out/name
    directory.mkdir()
    for filename in ['ivy.lock.xml', 'ant-purifier.lock.json', 'ant-purifier.lock.json.payload.json']:
        (directory/filename).write_bytes((out/'project'/filename).read_bytes())
def native(name, home):
    run(name, [context['ant']['output']+'/bin/ant', 'resolve'], dict(ANT_OPTS='-Duser.home='+str(home)))
    report = ET.parse(home/'.ivy2/cache/example-legacy-proof-default.xml').getroot()
    return {m.get('organisation')+':'+m.get('name'): r.get('name') for m in report.findall('./dependencies/module')
            for r in m.findall('revision') if not r.get('evicted')}
try:
    initial_native = native('native-initial', out/'native-warm-home')
    run('capture', [a.cli, 'lock'])
    initial = selected()
    snapshot('initial-lock')
    assert initial == initial_native == {'example:middle':'1.0', 'example:shared':'2.0'}
    jar = fixture.module(out/'repository', context['sdk']['home'], 'shared', '3.0',
                         'package example; public class Shared { public static int value(){return 3;} }')
    warm = native('native-warm-after-new-release', out/'native-warm-home')
    fresh = native('native-fresh-after-new-release', out/'native-fresh-home')
    assert fresh['example:shared'] == '3.0'
    before = {name:(out/'project'/name).read_bytes() for name in
              ['ivy.lock.xml','ant-purifier.lock.json','ant-purifier.lock.json.payload.json']}
    run('sticky-lock', [a.cli, 'lock'])
    snapshot('sticky-lock-files')
    assert selected() == initial
    assert all((out/'project'/name).read_bytes() == value for name,value in before.items())
    run('named-update', [a.cli, 'update', 'example:shared'])
    snapshot('named-update-files')
    assert selected() == fresh
    before = {name:(out/'project'/name).read_bytes() for name in before}
    with zipfile.ZipFile(jar, 'a') as archive: archive.writestr('changed.txt', 'actual upstream bytes changed')
    run('changed-pinned-artifact', [a.cli, 'lock'], error='artifact changed bytes')
    snapshot('failed-lock-files')
    assert all((out/'project'/name).read_bytes() == value for name,value in before.items())
    run('explicit-update-changed-bytes', [a.cli, 'update', 'example:shared'])
    snapshot('explicit-byte-update-files')
    assert selected() == fresh
    (out/'result.json').write_text(json.dumps(dict(status='passed', stages=results, nativeInitial=initial_native,
        nativeWarmAfterRelease=warm, nativeFreshAfterRelease=fresh, stickyRelockByteIdentical=True,
        namedUpdateUsesNativeNewRevision=True, changedArtifactRejectedWithoutWriting=True,
        explicitUpdateAcceptsChangedBytes=True, scope='Exact Ant 1.5.4/Ivy 2.4.0/SDK6; no shared Ivy assumption'),indent=2)+'\n')
finally:
    server.shutdown()
    server.server_close()
