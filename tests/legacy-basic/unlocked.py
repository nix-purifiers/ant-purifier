#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ordinary wrapper fallback, with strict explicit and partial-lock operations."""
import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
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
    def log_message(self, *unused):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(out/'repository')))
threading.Thread(target=server.serve_forever, daemon=True).start()
fixture.project(out/'original', 'http://127.0.0.1:'+str(server.server_port), context)
env = dict(os.environ, ANT_OPTS='-Duser.home='+str(out/'native-home'), CLASSPATH=context['ivy']['output'],
           LEGACY_UNLOCKED_ENV='literal environment:$value', XDG_CACHE_HOME=str(out/'cache'))
for key in ['JAVACMD', 'ANT_ARGS']:
    env.pop(key, None)
results = []


def run(name, root, argv, success):
    result = subprocess.run(list(map(str, argv)), cwd=root, env=env, capture_output=True, text=True, timeout=180)
    log = result.stdout+result.stderr
    (out/(name+'.log')).write_text(log)
    assert (result.returncode == 0) == success, log
    assert ('no lockfile; using ordinary impure Ant/Ivy' in log) == success, log
    results.append(dict(name=name, exitCode=result.returncode, fallbackWarning=success))
    return log


try:
    root = out/'unlocked'
    shutil.copytree(out/'original', root)
    build = root/'build.xml'
    build.write_text(build.read_text().replace('</project>', '''
<target name="unlocked-check" depends="test"><property environment="env"/>
<echo file="unlocked-argv.txt" message="${unlocked.arg}|${env.LEGACY_UNLOCKED_ENV}"/></target>
</project>'''))
    log = run('ordinary-ant', root, [a.cli.parent/'ant', '-Dunlocked.arg=literal spaces:$value', 'unlocked-check'], True)
    assert 'LEGACY SDK6 CONFLICT AND JAVAEXEC PASSED' in log
    assert (root/'unlocked-argv.txt').read_text() == 'literal spaces:$value|literal environment:$value'
    assert (root/'test-started').exists()
    names = ['ivy.lock.xml', 'ant-purifier.lock.json', 'ant-purifier.lock.json.payload.json']
    assert not any((root/name).exists() for name in names)
    root = out/'explicit-prefetch'
    shutil.copytree(out/'original', root)
    run('explicit-prefetch', root, [a.cli, 'prefetch'], False)
    assert not (root/'build').exists()
    for index, name in enumerate(names):
        root = out/('partial-'+str(index))
        shutil.copytree(out/'original', root)
        (root/name).write_text('invalid partial lock')
        run('partial-'+str(index), root, [a.cli.parent/'ant', 'test'], False)
        assert not (root/'build').exists() and not (root/'test-started').exists()
    (out/'result.json').write_text(json.dumps(dict(status='passed', stages=results,
        nativeCompileAndSdk6JavaExec=True, originalArgvAndEnvironmentPreserved=True,
        noLocksCreated=True, partialLocksRejectedBeforeActions=True), indent=2)+'\n')
finally:
    server.shutdown()
    server.server_close()
