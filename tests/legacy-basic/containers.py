#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject task containers before earlier selected-target actions execute."""
import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import fixture
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--cli',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
exports=dict(re.findall(r"^export ([A-Z_]+)='([^']*)'",a.cli.read_text(),re.M))
context=json.loads(Path(exports['ANT_PURIFIER_LEGACY_CONTEXT']).read_text())
fixture.repository(out/'repository',context)
class Handler(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*unused):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(out/'repository')))
threading.Thread(target=server.serve_forever,daemon=True).start()
results=[]
try:
 for container in ['sequential','parallel']:
  root=out/container;fixture.project(root,'http://127.0.0.1:'+str(server.server_port),context)
  build=root/'build.xml'
  build.write_text(build.read_text().replace('</project>',
      '<target name="nested-package"><touch file="early-action"/><'+container+'><jar jarfile="nested.jar" basedir="src"/></'+container+'></target></project>'))
  env=dict(os.environ,XDG_CACHE_HOME=str(out/'cache'))
  for key in ['JAVACMD','ANT_ARGS','ANT_OPTS']:env.pop(key,None)
  for command in ['lock','prefetch','native']:
   argv=[str(a.cli),command]+(['--','nested-package'] if command=='native' else [])
   r=subprocess.run(argv,cwd=root,env=env,capture_output=True,text=True,timeout=300)
   log=r.stdout+r.stderr;(out/(container+'-'+command+'.log')).write_text(log)
   if command=='native':
    assert r.returncode!=0,log
    assert not (root/'early-action').exists(), 'preflight allowed an earlier action before nested '+container+' packaging rejection'
    assert not (root/'nested.jar').exists()
    assert 'does not support task containers' in log,log
   else:assert r.returncode==0,log
  results.append(dict(container=container,rejectedBeforeEarlierAction=True))
  print(container,'passed',flush=True)
 (out/'result.json').write_text(json.dumps(results,indent=2)+'\n')
finally:
 server.shutdown();server.server_close()
