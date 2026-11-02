#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise native Ant/Ivy pinning, updates, external locks and fallback."""
import functools,http.server,json,os,shutil,subprocess,sys,tempfile,threading,xml.etree.ElementTree as ET
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from ant_purifier import editor

def run(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,text=True,**kwargs)
case=sys.argv[1]
system=run(['nix','eval','--impure','--raw','--expr','builtins.currentSystem'],capture_output=True).stdout.strip()
with tempfile.TemporaryDirectory(prefix='ant-conformance-') as tmp:
 temp=Path(tmp);cli=temp/'cli';run(['nix','build',str(REPO)+'#cli','--out-link',cli])
 tools=json.loads(run(['nix','eval','--json',str(REPO)+'#packages.'+system+'.cli.purifierRuntime'],capture_output=True).stdout)
 purifier=cli/'bin/ant-purifier';ant=cli/'bin/ant'
 if case=='native':
  root=temp/'project';shutil.copytree(REPO/'examples/minimal',root,ignore=shutil.ignore_patterns('build','.ant-purifier','.classpath','.project'))
  original='<classpath><classpathentry kind="src" path="src"/><classpathentry kind="con" path="org.apache.ivyde.eclipse.cpcontainer.IVYDE_CONTAINER"/><classpathentry kind="output" path="build/classes"/></classpath>\n'
  (root/'.classpath').write_text(original)
  envpath=Path(run([purifier,'--project',root,'prefetch','--print-environment'],capture_output=True).stdout.strip())
  editor.prepare(root,envpath);assert 'sourcepath=' in (root/'.classpath').read_text()
  output=run([ant,'-f',root/'build.xml','test'],cwd=root,capture_output=True).stdout
  assert 'Locked dependencies' in output,output
  output=run([ant,'-find','build.xml','test'],cwd=root/'src',capture_output=True).stdout
  assert 'Locked dependencies' in output,output
  properties=root/'build.properties';before=properties.read_text();properties.write_text(before+'\n# changed\n')
  invalid=subprocess.run([str(ant),'-f',str(root/'build.xml'),'test'],cwd=root,text=True,capture_output=True)
  assert invalid.returncode and 'ordinary impure' not in invalid.stderr
  properties.write_text(before);(root/'ant-purifier.lock.json').unlink()
  fallback=run([ant,'-version'],cwd=root,capture_output=True)
  assert 'Apache Ant' in fallback.stdout and 'ordinary impure Ant/Ivy' in fallback.stderr
  assert (root/'.classpath').read_text()==original and not (root/'.project').exists()
  unlocked=temp/'unlocked';unlocked.mkdir()
  (unlocked/'build.xml').write_text('<project default="fail"><target name="fail"><fail status="7" message="native failure"/></target></project>')
  failure=subprocess.run([str(ant),'fail'],cwd=unlocked,text=True,capture_output=True)
  assert failure.returncode==7 and 'ordinary impure Ant/Ivy' in failure.stderr
  assert not (unlocked/'ant-purifier.lock.json').exists()
 else:
  root=temp/'project';root.mkdir();served=temp/'repository';served.mkdir()
  versions={name:['1.0'] for name in ('first','second')}
  def release(name,version,value):
   package=served/'fixture'/name/version;package.mkdir(parents=True,exist_ok=True)
   work=temp/(name+'-'+version);(work/'src').mkdir(parents=True);(work/'classes').mkdir()
   cls=name.capitalize();source=work/'src'/(cls+'.java')
   source.write_text('package fixture; public final class '+cls+' { public static String value() {return "'+value+'";} }')
   run([Path(tools['javaHome'])/'bin/javac','--release','11','-d',work/'classes',source],capture_output=True)
   run([Path(tools['javaHome'])/'bin/jar','--create','--date=1980-01-01T00:00:02Z','--file',package/(name+'-'+version+'.jar'),'-C',work/'classes','.'],capture_output=True)
   (package/(name+'-'+version+'.pom')).write_text('<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>fixture</groupId><artifactId>'+name+'</artifactId><version>'+version+'</version></project>')
   (served/'fixture'/name/'maven-metadata.xml').write_text('<metadata><groupId>fixture</groupId><artifactId>'+name+'</artifactId><versioning><latest>'+version+'</latest><release>'+version+'</release><versions>'+''.join('<version>'+v+'</version>' for v in versions[name])+'</versions></versioning></metadata>')
  for name in versions:release(name,'1.0','one')
  class Quiet(http.server.SimpleHTTPRequestHandler):
   def log_message(self,*_):pass
  server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=served))
  worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
  try:
   shutil.copyfile(REPO/'tests/consumer/build.xml',root/'build.xml')
   # Keep the fixture native: init -> resolve -> compile -> test.
   (root/'build.xml').write_text('<project default="test" xmlns:ivy="antlib:org.apache.ivy.ant"><target name="resolve"><ivy:settings file="ivysettings.xml"/><ivy:resolve/><ivy:cachepath pathid="dependencies"/></target><target name="test" depends="resolve"><mkdir dir="build/classes"/><javac srcdir="src" destdir="build/classes" includeantruntime="false"><classpath refid="dependencies"/></javac><java classname="Main" failonerror="true"><classpath><pathelement location="build/classes"/><path refid="dependencies"/></classpath></java></target></project>')
   (root/'src').mkdir();(root/'src/Main.java').write_text('import fixture.First; import fixture.Second; public final class Main { public static void main(String[] args) {System.out.println("VALUES="+First.value()+"-"+Second.value());} }')
   (root/'ivy.xml').write_text('<ivy-module version="2.0"><info organisation="fixture" module="app" revision="1.0"/><dependencies>'+''.join('<dependency org="fixture" name="'+name+'" rev="latest.integration" conf="default->default"/>' for name in versions)+'</dependencies></ivy-module>')
   (root/'ivysettings.xml').write_text('<ivysettings><settings defaultResolver="fixture"/><resolvers><ibiblio name="fixture" m2compatible="true" root="http://127.0.0.1:'+str(server.server_port)+'/"/></resolvers></ivysettings>')
   args=[purifier,'--project',root];native=root/'ivy.lock.xml';sidecar=root/'ant-purifier.lock.json'
   run([*args,'lock']);first=sidecar.read_bytes();native_first=native.read_bytes()
   run([*args,'lock']);assert sidecar.read_bytes()==first and native.read_bytes()==native_first
   original=json.loads(first)
   for name in versions:versions[name].append('2.0');release(name,'2.0','two')
   run([*args,'lock']);assert sidecar.read_bytes()==first
   if case=='update':
    run([*args,'update','first']);changed=json.loads(sidecar.read_text())
    chosen={m['name']:m['version'] for m in changed['modules']};assert chosen=={'first':'2.0','second':'1.0'},chosen
    run([*args,'update']);chosen={m['name']:m['version'] for m in json.loads(sidecar.read_text())['modules']};assert chosen=={'first':'2.0','second':'2.0'},chosen
   elif case=='relock':
    damaged=json.loads(first);damaged['contentHash']='bad';sidecar.write_text(json.dumps(damaged));run([*args,'lock'])
    assert {m['version'] for m in json.loads(sidecar.read_text())['modules']}=={'1.0'}
    native.write_text('broken native XML');run([*args,'lock'])
    assert {m['version'] for m in json.loads(sidecar.read_text())['modules']}=={'1.0'}
   elif case=='external':
    native=temp/'external/ivy.xml';sidecar=temp/'external/ant.json';args=[*args,'--native-lock',native,'--lockfile',sidecar]
    run([*args,'lock']);assert {m['version'] for m in json.loads(sidecar.read_text())['modules']}=={'1.0'}
    assert (root/'ivy.lock.xml').read_bytes()==native_first and (root/'ant-purifier.lock.json').read_bytes()==first
    (root/'ivy.lock.xml').unlink();(root/'ant-purifier.lock.json').unlink()
   run([*args,'prefetch'])
  finally:server.shutdown();server.server_close();worker.join()
  env={**os.environ,'ANT_PURIFIER_NATIVE_LOCKFILE':str(native),'ANT_PURIFIER_LOCKFILE':str(sidecar)}
  output=run([ant,'-f',root/'build.xml','test'],env=env,cwd=root,capture_output=True).stdout
  assert ('VALUES=two-two' if case=='update' else 'VALUES=one-one') in output,output
 print('PASS',case)
