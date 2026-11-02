# SPDX-License-Identifier: MIT
import argparse,base64,hashlib,json,os,shlex,shutil,subprocess,sys,tempfile,xml.etree.ElementTree as ET
from pathlib import Path
from . import lock
ANT=os.environ.get('ANT_PURIFIER_ANT','ant')
JAVA=os.environ.get('ANT_PURIFIER_JAVA','java')
def run(args,**kw):return subprocess.run(list(map(str,args)),check=True,**kw)
def read(path):return json.loads(path.read_text())
def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as stream:stream.write(text);temporary=Path(stream.name)
 temporary.replace(path)
def sri(path):return 'sha256-'+base64.b64encode(hashlib.sha256(Path(path).read_bytes()).digest()).decode()
def checked(root,native,sidecar,ivy,build):
 data=read(sidecar)
 if problems:=lock.problems(root,native,data,ivy=ivy,build=build):raise ValueError('\n'.join(problems))
 return data
def toolchain():return {k:os.environ['ANT_PURIFIER_'+env] for k,env in [('antVersion','ANT_VERSION'),('ivyVersion','IVY_VERSION'),('javaVersion','JAVA_VERSION'),('resolverVersion','RESOLVER_VERSION')]}
def property_hashes(properties):
 result=[]
 for value in properties:
  name,separator,content=value.partition('=')
  if not separator or not name:raise ValueError('expected Ant property NAME=VALUE')
  result.append({'name':name,'hash':hashlib.sha256(content.encode()).hexdigest()})
 return result
def do_lock(root,ivy,build,native,sidecar,target,update=False,names=(),properties=()):
 properties=[v[2:] for v in shlex.split(os.environ.get('ANT_ARGS','')) if v.startswith('-D')]+list(properties)
 property_fingerprints=property_hashes(properties)
 previous=None
 if sidecar.exists():
  try:
   candidate=read(sidecar)
   if not isinstance(candidate,dict):raise ValueError('invalid companion format')
   if candidate.get('contentHash')==lock.seal(candidate)['contentHash']:previous=candidate
   if not update and all(candidate.get(k)==v for k,v in toolchain().items()) and not lock.problems(root,native,candidate,ivy=ivy,build=build):
    if candidate['resolveTarget']==target and candidate.get('properties',[])==property_fingerprints:print('Existing native resolution retained',file=sys.stderr);return
  except (ValueError,OSError,TypeError):pass
 if names and not previous:raise ValueError('named updates require an existing valid companion'+lock.FIX)
 selected=set()
 if names:
  for name in names:
   matching={lock.key(m) for m in previous['modules'] if name in (m['name'],lock.key(m))}
   if len(matching)!=1:raise ValueError('update name is absent or ambiguous; use group:module: '+name)
   selected.update(matching)
 with tempfile.TemporaryDirectory(prefix='ant-purifier-lock-') as tmp:
  temp=Path(tmp);stage=temp/'project';shutil.copytree(root,stage,ignore=shutil.ignore_patterns(*lock.IGNORED))
  staged_ivy=stage/ivy.relative_to(root) if ivy.is_relative_to(root) else stage/'ivy.xml'
  staged_build=stage/build.relative_to(root) if build.is_relative_to(root) else stage/'build.xml'
  for source,destination in ((ivy,staged_ivy),(build,staged_build)):
   destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
  prior=temp/'previous.xml'
  seed=native if native.exists() else root/'ivy.lock.xml'
  if seed.exists():
   try:lock.pins(seed);shutil.copyfile(seed,prior)
   except (ValueError,ET.ParseError):pass
  if not prior.exists() and previous and previous.get('inputs')==lock.inputs(root,native):
   # Recover native pin loss from the selected graph while retaining the unchanged declaration.
   document=ET.parse(staged_ivy);dependencies=document.getroot().find('dependencies')
   if dependencies is None:dependencies=ET.SubElement(document.getroot(),'dependencies')
   for m in previous['modules']:ET.SubElement(dependencies,'override',{'org':m['group'],'module':m['name'],'matcher':'exact','rev':m['version']})
   prior=staged_ivy.with_name('.ant-purifier-previous.xml');document.write(prior,encoding='unicode')
  output=temp/'resolution';output.mkdir()
  env={**os.environ,'HOME':str(temp/'home'),'ANT_PURIFIER_LOCKING':'1'};Path(env['HOME']).mkdir()
  command=[JAVA,*shlex.split(os.environ.get('ANT_OPTS','')),'-Djava.io.tmpdir='+str(temp),'-Duser.home='+env['HOME'],'-Dant.home='+os.environ['ANT_PURIFIER_ANT_HOME'],'-cp',os.environ['ANT_PURIFIER_LOCK_CLASSPATH'],'org.nixpurifiers.ant.AntResolve',staged_ivy,output,prior,'all' if update and not names else 'selected' if update else 'none',','.join(sorted(selected)),','.join(lock.key(m) for m in previous['modules']) if previous else ','.join(lock.pins(prior)) if prior.exists() else '',staged_build,target,*properties]
  run(command,cwd=stage,env=env,stdout=sys.stderr)
  resolution=ET.parse(output/'resolution.xml').getroot();modules=[];artifacts=[];metadata=[]
  for record in resolution.findall('./modules/module'):
   m={key:record.get(key) for key in ('group','name','version')};m['descriptor']=Path(record.get('file')).read_text()
   if (original:=record.find('original')) is not None:m['original']={'url':original.get('url'),'hash':sri(original.get('file'))}
   old=next((p for p in (previous or {}).get('modules',[]) if all(p[k]==m[k] for k in ('group','name','version'))),None)
   updating=update and (not names or lock.key(m) in selected)
   if old and old.get('original') and m.get('original') and old['original']['hash']!=m['original']['hash'] and not updating:raise ValueError('a pinned native module descriptor changed bytes: '+lock.key(m)+'; use an explicit update')
   if old and old.get('original',{}).get('hash')==m.get('original',{}).get('hash'):m['descriptor']=old['descriptor']
   modules.append(m)
  for record in resolution.findall('./artifacts/artifact'):
   a={k:v for k,v in record.attrib.items() if k!='file'};a['hash']=sri(record.get('file'))
   old=next((p for p in (previous or {}).get('artifacts',[]) if all(p[k]==a[k] for k in ('group','module','version','name','ext','classifier'))),None)
   if old and old['hash']!=a['hash'] and not (update and (not names or a['group']+':'+a['module'] in selected)):raise ValueError('a pinned native artifact changed bytes: '+a['path']+'; use an explicit update to accept the change')
   artifacts.append(a)
  unique={}
  for artifact in artifacts:
   prior_artifact=unique.get(artifact['path'])
   if prior_artifact and prior_artifact['hash']!=artifact['hash']:raise ValueError('native artifacts collide at '+artifact['path'])
   if not prior_artifact or (artifact['type'],artifact['url'])<(prior_artifact['type'],prior_artifact['url']):unique[artifact['path']]=artifact
  artifacts=list(unique.values())
  for record in resolution.findall('./metadata/pom'):
   m={k:v for k,v in record.attrib.items() if k!='file'};m['hash']=sri(record.get('file'));metadata.append(m)
  staged_native=output/'ivy.lock.xml'
  data=lock.seal({'version':1,**toolchain(),'nativeHash':lock.digest(staged_native),'ivyHash':lock.digest(ivy),'buildHash':lock.digest(build),'inputs':lock.inputs(root,native),'ivyFile':str(ivy.relative_to(root)) if ivy.is_relative_to(root) else ivy.name,'buildFile':str(build.relative_to(root)) if build.is_relative_to(root) else build.name,'resolveTarget':target,'properties':property_fingerprints,'modules':sorted(modules,key=lock.key),'artifacts':sorted(artifacts,key=lambda a:a['path']),'metadata':sorted(metadata,key=lambda m:(lock.key(m),m['version'])),'sourceRoots':sorted({s.get('path') for s in resolution.findall('./sourceRoots/source')})})
  if problems:=lock.problems(root,staged_native,data,input_native=native,ivy=ivy,build=build):raise ValueError('\n'.join(problems))
  write(native,staged_native.read_text());write(sidecar,json.dumps(data,sort_keys=True,indent=2)+'\n')
 print('Locked native Ivy graph',file=sys.stderr)
def realize(root,ivy,build,native,sidecar,target):
 return Path(run(['nix','build','--impure','--file',os.environ['ANT_PURIFIER_REALIZE'],'--argstr','project',root,'--argstr','ivyFile',ivy,'--argstr','buildFile',build,'--argstr','ivyLock',native,'--argstr','lockFile',sidecar,'--argstr','target',target,'--no-link','--print-out-paths'],text=True,stdout=subprocess.PIPE).stdout.strip())
def prefetch(root,ivy,build,native,sidecar):
 checked(root,native,sidecar,ivy,build)
 cache=sidecar.parent/'.ant-purifier'/hashlib.sha256(str(sidecar).encode()).hexdigest()[:12];cache.mkdir(parents=True,exist_ok=True)
 for target in ('environment','runtime'):
  output=realize(root,ivy,build,native,sidecar,target)
  run(['nix-store','--add-root',cache/target,'--indirect','--realise',output],stdout=subprocess.DEVNULL)
 return (cache/'environment').resolve()
def project_from_args(arguments):
 supplied=shlex.split(os.environ.get('ANT_ARGS',''))+arguments;build=None;find=None
 for i,a in enumerate(supplied):
  if a in ('-f','-file','-buildfile') and i+1<len(supplied):build=Path(supplied[i+1]).expanduser().resolve()
  if a in ('-find','-s'):find=supplied[i+1] if i+1<len(supplied) and not supplied[i+1].startswith('-') else 'build.xml'
 if build:return build.parent,build
 if find:
  for directory in [Path.cwd(),*Path.cwd().parents]:
   if (directory/find).exists():return directory,(directory/find)
 return Path.cwd(),Path.cwd()/'build.xml'
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--project');parser.add_argument('--ivy-file',default=os.environ.get('ANT_PURIFIER_IVY_FILE'));parser.add_argument('--build-file');parser.add_argument('--native-lock',default=os.environ.get('ANT_PURIFIER_NATIVE_LOCKFILE'));parser.add_argument('--lockfile',default=os.environ.get('ANT_PURIFIER_LOCKFILE'));parser.add_argument('--resolve-target',default='resolve');parser.add_argument('-D','--property',action='append',default=[])
 sub=parser.add_subparsers(dest='command',required=True);sub.add_parser('lock');p=sub.add_parser('update');p.add_argument('names',nargs='*');p=sub.add_parser('prefetch');p.add_argument('--print-environment',action='store_true');p=sub.add_parser('native');p.add_argument('args',nargs=argparse.REMAINDER);p=sub.add_parser('editor');p.add_argument('args',nargs=argparse.REMAINDER)
 a=parser.parse_args();arguments=(a.args[1:] if a.args[:1]==['--'] else a.args) if a.command in ('native','editor') else []
 root,build=project_from_args(arguments)
 if a.project:root=Path(a.project).expanduser().resolve();build=root/'build.xml'
 if a.build_file:build=Path(a.build_file).expanduser().resolve()
 ivy=Path(a.ivy_file).expanduser().resolve() if a.ivy_file else root/'ivy.xml'
 native=Path(a.native_lock).expanduser().resolve() if a.native_lock else root/'ivy.lock.xml'
 sidecar=Path(a.lockfile).expanduser().resolve() if a.lockfile else root/'ant-purifier.lock.json'
 if a.command=='editor':
  from . import editor
  worker=os.environ['ANT_PURIFIER_JDTLS']
  if not sidecar.exists():
   editor.restore(root)
   print('ant-purifier: no lockfile; using ordinary impure Java tooling',file=sys.stderr)
   os.execv(worker,[worker,*arguments])
  editor.prepare(root,prefetch(root,ivy,build,native,sidecar))
  cache=Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'ant-purifier/jdtls'/hashlib.sha256(str(root).encode()).hexdigest()
  cache.mkdir(parents=True,exist_ok=True)
  if not any(v in ('-data','--data') or v.startswith(('-data=','--data=')) for v in arguments):arguments=['-data',str(cache),*arguments]
  os.environ.update(editor.worker_cache(cache))
  os.execv(worker,[worker,*arguments])
 elif a.command=='native':
  if not sidecar.exists():
   from . import editor
   editor.restore(root)
   print('ant-purifier: no lockfile; using ordinary impure Ant/Ivy',file=sys.stderr);os.execv(ANT,[ANT,*arguments])
  if any(flag in arguments for flag in ('-version','-help','-h','-diagnostics')):os.execv(ANT,[ANT,*arguments])
  environment=prefetch(root,ivy,build,native,sidecar)
  os.environ.update(ANT_PURIFIER_ENVIRONMENT=str(environment),ANT_PURIFIER_IVY_FILE=str(ivy),ANT_PURIFIER_NIX_DELIVERED='1',ANT_PURIFIER_PROJECT_ROOT=str(root))
  os.execv(ANT,[ANT,'-lib',os.environ['ANT_PURIFIER_PLUGIN'],'-lib',os.environ['ANT_PURIFIER_IVY_JAR'],'-listener','org.nixpurifiers.ant.LockedListener',*arguments])
 elif a.command in ('lock','update'):do_lock(root,ivy,build,native,sidecar,a.resolve_target,a.command=='update',getattr(a,'names',()),a.property)
 else:print(prefetch(root,ivy,build,native,sidecar))
