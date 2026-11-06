#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exact native control and legacy CLI lifecycle; no version-range inference."""
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import xml.etree.ElementTree as ET
import fixture

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cli', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--namespace-tools', default='/nix/store/0bmapmnznzaxgx76jhzbznhlwq738g03-util-linux-2.42.3-bin/bin/unshare')
parser.add_argument('--ip', default='/nix/store/1cl0hbvjcgy95vskd4q0cbspc1yly8ir-iproute2-7.1.0/bin/ip')
args = parser.parse_args()
cli = args.cli.resolve()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
match = re.search(r"^export ANT_PURIFIER_LEGACY_CONTEXT='([^']+)'", cli.read_text(), re.M)
assert match, 'CLI source-owned context binding is missing'
context_file = Path(match.group(1))
context = json.loads(context_file.read_text())
sdk, ant = context['sdk']['home'], context['ant']['output']
fixture.repository(out/'repository', context)
requests = []


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *unused):
        pass

    def do_GET(self):
        requests.append(self.path)
        super().do_GET()


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(out/'repository')))
threading.Thread(target=server.serve_forever, daemon=True).start()
fixture.project(out/'project', 'http://127.0.0.1:'+str(server.server_port), context)
shutil.copytree(out/'project', out/'native')
originals = {str(p.relative_to(out/'project')): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (out/'project').rglob('*') if p.is_file()}
env = dict(os.environ, JAVA_HOME=sdk, ANT_HOME=ant+'/share/ant',
           XDG_CACHE_HOME=str(out/'cache'))
env.pop('JAVACMD', None)
env.pop('ANT_ARGS', None)
env.pop('ANT_OPTS', None)
stages = []


def run(name, command, cwd, extra=None):
    command = list(map(str, command))
    with (out/(name+'.log')).open('w') as log:
        result = subprocess.run(command, cwd=cwd, env=dict(env, **(extra or {})),
                                stdout=log, stderr=subprocess.STDOUT, timeout=600)
    stages.append(dict(name=name, argv=command, exitCode=result.returncode))
    (out/'stages.json').write_text(json.dumps(stages, indent=2)+'\n')
    print(name, result.returncode, flush=True)
    assert result.returncode == 0, (name, (out/(name+'.log')).read_text()[-8000:])


stopped = False
try:
    run('native-version', [ant+'/bin/ant', '-version'], out/'native')
    run('native-test', [ant+'/bin/ant', '-verbose', 'test'], out/'native',
        dict(ANT_OPTS='-Duser.home='+str(out/'native-home'), CLASSPATH=context['ivy']['output']))
    native_report = ET.parse(out/'native-home/.ivy2/cache/example-legacy-proof-default.xml').getroot()
    selected = {(m.get('organisation'), m.get('name'), r.get('name'))
                for m in native_report.findall('./dependencies/module')
                for r in m.findall('revision') if not r.get('evicted')}
    evicted_edges = [dict(module=m.get('name'), revision=r.get('name'), by=[x.get('rev') for x in r.findall('evicted-by')],
                          callers=[dict(x.attrib) for x in r.findall('caller')])
                     for m in native_report.findall('./dependencies/module')
                     for r in m.findall('revision') if r.get('evicted')]
    assert selected == {('example', 'middle', '1.0'), ('example', 'shared', '2.0')}
    assert any(x['module']=='shared' and x['revision']=='1.0' and x['by']==['2.0'] for x in evicted_edges)
    run('capture', [cli, 'lock'], out/'project')
    files = ['ivy.lock.xml', 'ant-purifier.lock.json', 'ant-purifier.lock.json.payload.json']
    captured = {name: (out/'project'/name).read_bytes() for name in files}
    outer = json.loads(captured['ant-purifier.lock.json'])
    payload = json.loads(captured['ant-purifier.lock.json.payload.json'])
    assert outer['runtimeContext'] == context
    assert {(m['group'],m['name'],m['version']) for m in payload['modules']} == selected
    for artifact in payload['artifacts']:
        native = out/'native/build/deps'/(artifact['name']+'-'+artifact['version']+'.'+artifact['ext'])
        assert artifact['hash'] == 'sha256-'+__import__('base64').b64encode(hashlib.sha256(native.read_bytes()).digest()).decode()
    run('actual-relock', [cli, 'lock'], out/'project')
    assert all((out/'project'/name).read_bytes()==value for name,value in captured.items())
    cold = out/'relocated'
    shutil.copytree(out/'project', cold, ignore=shutil.ignore_patterns('.ant-purifier', 'build', 'target'))
    run('relocated-relock', [cli, 'lock'], cold)
    assert all((cold/name).read_bytes()==value for name,value in captured.items())
    run('prefetch', [cli, 'prefetch'], cold)
    server.shutdown()
    server.server_close()
    stopped = True
    before = len(requests)
    assert not (cold/'build').exists()
    namespace = [args.namespace_tools, '-rn', 'sh', '-c', args.ip+' link set lo up && exec "$@"', 'ant-legacy-offline']
    run('cold-native-test', [*namespace, cli, 'native', '--', 'test'], cold)
    assert len(requests) == before
    assert 'LEGACY SDK6 CONFLICT AND JAVAEXEC PASSED' in (out/'cold-native-test.log').read_text()
    for artifact in payload['artifacts']:
        name = artifact['name']+'-'+artifact['version']+'.'+artifact['ext']
        assert (cold/'build/deps'/name).read_bytes() == (out/'native/build/deps'/name).read_bytes()
    assert (cold/'build/classes/example/Main.class').read_bytes() == (out/'native/build/classes/example/Main.class').read_bytes()
    assert all(hashlib.sha256((out/'project'/name).read_bytes()).hexdigest()==digest
               and hashlib.sha256((cold/name).read_bytes()).hexdigest()==digest for name,digest in originals.items())
    (out/'result.json').write_text(json.dumps(dict(status='passed', sourceOwnedRuntime=context,
        nativeSelected=sorted(selected), evictedEdges=evicted_edges, actualRelockByteIdentical=True,
        relocatedRelockByteIdentical=True, sourcePreserved=True, coldCacheInitiallyAbsent=True,
        originStopped=True, networkNamespace=True, nativeArtifactBytesEqual=True, nativeClassBytesEqual=True,
        actualSdk6JavaExecExecuted=True, scope='CLI lifecycle only; pure builder/rebuild/negatives/modern baseline still separate'), indent=2)+'\n')
finally:
    if not stopped:
        server.shutdown()
        server.server_close()
