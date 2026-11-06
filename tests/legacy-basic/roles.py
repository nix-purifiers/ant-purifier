#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Capture source-declared foreign roles, then reject them before role actions."""
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
p.add_argument('--foreign-sdk',type=Path,required=True)
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
 for role in ['compiler','runtime']:
  root=out/role;fixture.project(root,'http://127.0.0.1:'+str(server.server_port),context)
  build=root/'build.xml';text=build.read_text()
  if role=='compiler':text=text.replace('<javac srcdir=', '<javac fork="true" executable="'+str(a.foreign_sdk/'bin/javac')+'" srcdir=')
  else:text=text.replace('jvm="${java.home}/bin/java"','jvm="'+str(a.foreign_sdk/'bin/java')+'"')
  build.write_text(text)
  env=dict(os.environ,XDG_CACHE_HOME=str(out/'cache'))
  for key in ['JAVACMD','ANT_ARGS','ANT_OPTS']:env.pop(key,None)
  for command in ['lock','prefetch','native']:
   argv=[str(a.cli),command]+(['--','test'] if command=='native' else [])
   r=subprocess.run(argv,cwd=root,env=env,capture_output=True,text=True,timeout=300)
   log=r.stdout+r.stderr;(out/(role+'-'+command+'.log')).write_text(log)
   if command=='native':
    assert r.returncode!=0 and ('legacy compiler differs' if role=='compiler' else 'legacy Java task runtime differs') in log,log
    assert not (root/'test-started').exists()
    if role=='compiler':assert not (root/'build/classes/example/Main.class').exists()
    else:assert (root/'build/classes/example/Main.class').exists()
   else:assert r.returncode==0,log
  results.append(dict(role=role,foreignSdk=str(a.foreign_sdk),sourceCapturedWithoutRewriting=True,
                      beforeRoleActionRejected=True))
  print(role,'passed',flush=True)
 (out/'result.json').write_text(json.dumps(results,indent=2)+'\n')
finally:
 server.shutdown();server.server_close()
