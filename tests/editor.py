# SPDX-License-Identifier: MIT
"""Exercise real JDT resolution and source retrieval with no network."""
import json,os,select,subprocess,sys,time
from pathlib import Path
from ant_purifier import editor
root=Path.cwd();editor.prepare(root,Path(sys.argv[1]));os.environ.update(editor.worker_cache(Path(os.environ['TMPDIR'])/'jdt-workspace'))
log=(root/'.ant-purifier/jdt-server.log').open('w')
server=subprocess.Popen([os.environ['ANT_PURIFIER_JDTLS'],'--jvm-arg=-Djava.io.tmpdir='+os.environ['TMPDIR'],'-data',str(Path(os.environ['TMPDIR'])/'jdt-workspace')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
pending=b''
def send(message):
 payload=json.dumps({'jsonrpc':'2.0',**message}).encode();server.stdin.write(f'Content-Length: {len(payload)}\r\n\r\n'.encode()+payload);server.stdin.flush()
def receive():
 global pending
 deadline=time.monotonic()+45
 while True:
  if b'\r\n\r\n' in pending:
   headers,body=pending.split(b'\r\n\r\n',1);length=int(next(line.split(b':',1)[1] for line in headers.split(b'\r\n') if line.lower().startswith(b'content-length:')))
   if len(body)>=length:pending=body[length:];return json.loads(body[:length])
  remaining=deadline-time.monotonic()
  assert remaining>0 and select.select([server.stdout],[],[],remaining)[0],'JDT timed out'
  chunk=os.read(server.stdout.fileno(),65536);assert chunk,'JDT exited';pending+=chunk
settings={'java':{'import':{'maven':{'enabled':False},'gradle':{'enabled':False}},'maven':{'downloadSources':False},'autobuild':{'enabled':True}}}
def respond(message):
 if message.get('method')=='workspace/configuration':
  values=[]
  for item in message['params']['items']:
   value=settings
   for part in (item.get('section') or '').split('.'):
    if part:value=value.get(part) if isinstance(value,dict) else None
   values.append(value)
  send({'id':message['id'],'result':values})
 elif 'method' in message and 'id' in message:send({'id':message['id'],'result':None})
def reply(identifier):
 while True:
  message=receive();respond(message)
  if 'method' not in message and message.get('id')==identifier:
   assert 'error' not in message,message
   return message.get('result')
try:
 send({'id':1,'method':'initialize','params':{'processId':None,'rootUri':root.as_uri(),'workspaceFolders':[{'uri':root.as_uri(),'name':root.name}],'capabilities':{'workspace':{'configuration':True,'workspaceFolders':True}},'initializationOptions':{'settings':settings,'extendedClientCapabilities':{'classFileContentsSupport':True}}}})
 reply(1);send({'method':'initialized','params':{}})
 while True:
  message=receive();respond(message)
  if message.get('method')=='language/status' and message.get('params',{}).get('type')=='Started':break
 file=root/'src/Main.java';text=file.read_text();uri=file.as_uri()
 send({'method':'textDocument/didOpen','params':{'textDocument':{'uri':uri,'languageId':'java','version':1,'text':text}}})
 deadline=time.monotonic()+120;last=None
 while time.monotonic()<deadline:
  message=receive();respond(message)
  if message.get('method')=='textDocument/publishDiagnostics' and message['params']['uri']==uri:
   last=message['params']['diagnostics']
   if not any(d.get('severity',1)==1 for d in last):break
 else:raise AssertionError(last)
 lines=text.splitlines();line=next(i for i,v in enumerate(lines) if 'StringUtils.capitalize' in v)
 send({'id':2,'method':'textDocument/definition','params':{'textDocument':{'uri':uri},'position':{'line':line,'character':lines[line].index('capitalize')+2}}})
 definition=reply(2);assert 'StringUtils' in json.dumps(definition),definition
 location=definition[0] if isinstance(definition,list) else definition
 target=location.get('uri',location.get('targetUri'));assert target.startswith('jdt:'),target
 send({'id':3,'method':'java/classFileContents','params':{'uri':target}})
 source=reply(3);assert isinstance(source,str) and 'class StringUtils' in source and 'Licensed to the Apache Software Foundation' in source,'dependency sources were not available'
 workspace_log=Path(os.environ['TMPDIR'])/'jdt-workspace/.metadata/.log'
 if workspace_log.exists():
  events=workspace_log.read_text(errors='replace')
  assert 'UnknownHostException' not in events and 'Cannot download published Gradle versions' not in events,events
 send({'id':4,'method':'shutdown','params':None});reply(4);send({'method':'exit','params':None});server.stdin.close()
 # JDT 1.62 installs a non-daemon one-minute exit watchdog. Like a normal
 # LSP client, finish the process after the protocol shutdown completes.
 try:server.wait(timeout=5)
 except subprocess.TimeoutExpired:
  server.terminate()
  try:server.wait(timeout=10)
  except subprocess.TimeoutExpired:server.kill();server.wait()
finally:
 if server.poll() is None:server.kill();server.wait()
 log.close()
 if sys.exc_info()[0] is not None:
  for file in [root/'.classpath',root/'.project',root/'.ant-purifier/jdt-server.log',Path(os.environ['TMPDIR'])/'jdt-workspace/.metadata/.log']:
   if file.exists():print(str(file)+'\n'+file.read_text(errors='replace')[-6000:],file=sys.stderr)
print('JDT resolved locked imports and retrieved the prefetched dependency sources')
