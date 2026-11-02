# SPDX-License-Identifier: MIT
import hashlib,json,os,re,xml.etree.ElementTree as ET
from pathlib import Path
FIX='; run ant-purifier lock'
NAME=r'[A-Za-z0-9][A-Za-z0-9_.+-]*'
IGNORED={'.git','.ant-purifier','build','target','result','__pycache__','node_modules'}
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def seal(data):
 data={k:v for k,v in data.items() if k!='contentHash'}
 return {**data,'contentHash':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}
def inputs(root,native):
 result={}
 for directory,dirs,files in os.walk(root):
  dirs[:]=sorted(d for d in dirs if d not in IGNORED)
  for name in sorted(files):
   p=Path(directory)/name
   if p.resolve() in (native.resolve(),(root/'ivy.lock.xml').resolve()):continue
   if name.endswith(('.xml','.properties')):result[p.relative_to(root).as_posix()]=digest(p)
 return dict(sorted(result.items()))
def pins(native):
 root=ET.parse(native).getroot()
 if root.tag!='ivy-module' or root.get('version') not in ('2.0','2.2'):raise ValueError('unsupported native Ivy descriptor'+FIX)
 result={}
 for override in root.findall('./dependencies/override'):
  if override.get('matcher','exact')=='exact':
   org=override.get('org','');name=override.get('module','');rev=override.get('rev','')
   if all(re.fullmatch(NAME,v) for v in (org,name,rev)):result[org+':'+name]=rev
 return result
def key(m):return m['group']+':'+m['name']
def coordinate(m):return m['group'].replace('.','/')+'/'+m['name']+'/'+m['version']
def problems(root,native,data,input_native=None,ivy=None,build=None):
 try:
  native_pins=pins(native)
  if not isinstance(data,dict) or data.get('version')!=1:return ['unsupported companion format'+FIX]
  if data.get('contentHash')!=seal(data)['contentHash']:return ['contentHash mismatch'+FIX]
  if data.get('nativeHash')!=digest(native) or data.get('inputs')!=inputs(root,input_native or native):return ['configuration or native lock changed'+FIX]
  ivy=ivy or root/data['ivyFile'];build=build or root/data['buildFile']
  if data.get('ivyHash')!=digest(ivy) or data.get('buildHash')!=digest(build):return ['Ivy or Ant configuration changed'+FIX]
  modules=data.get('modules');artifacts=data.get('artifacts')
  if not isinstance(modules,list) or not isinstance(artifacts,list):return ['invalid dependency graph'+FIX]
  roots=data.get('sourceRoots')
  if not isinstance(roots,list) or not all(isinstance(p,str) and p and not Path(p).is_absolute() and '..' not in Path(p).parts for p in roots):return ['missing native source directories'+FIX]
  metadata=data.get('metadata')
  if not isinstance(metadata,list):return ['missing native POM metadata closure'+FIX]
  for m in metadata:
   if not all(isinstance(m.get(k),str) and re.fullmatch(NAME,m[k]) for k in ('group','name','version')) or not re.fullmatch(r'https?://[^/@\s]+/[^\s]*',m.get('url','')) or not re.fullmatch(r'sha256-[A-Za-z0-9+/]{43}=',m.get('hash','')):return ['invalid native POM metadata'+FIX]
  names=set();paths=set()
  for m in modules:
   if not all(isinstance(m.get(k),str) and re.fullmatch(NAME,m[k]) and m[k]!='..' for k in ('group','name','version')):return ['unsupported native coordinate'+FIX]
   identity=key(m)
   if identity in names or native_pins.get(identity)!=m['version']:return ['native pins do not match selected graph'+FIX]
   names.add(identity)
   if not isinstance(m.get('descriptor'),str):return ['missing native module descriptor'+FIX]
   descriptor=ET.fromstring(m['descriptor']);info=descriptor.find('info')
   if descriptor.tag!='ivy-module' or info is None or any(info.get(native_key)!=m[key] for native_key,key in [('organisation','group'),('module','name'),('revision','version')]):return ['native module descriptor coordinate mismatch'+FIX]
   original=m.get('original')
   if original and (not isinstance(original.get('url'),str) or not re.fullmatch(r'https?://[^/@\s]+/[^\s]*',original['url']) or not re.fullmatch(r'sha256-[A-Za-z0-9+/]{43}=',original.get('hash',''))):return ['invalid original metadata origin'+FIX]
  for a in artifacts:
   if not all(isinstance(a.get(k),str) and re.fullmatch(NAME,a[k]) and a[k]!='..' for k in ('group','module','version','name','ext','type')):return ['invalid artifact coordinates'+FIX]
   if a['group']+':'+a['module'] not in names or native_pins[a['group']+':'+a['module']]!=a['version']:return ['artifact is outside selected native graph'+FIX]
   if not isinstance(a.get('classifier'),str) or (a['classifier'] and not re.fullmatch(NAME,a['classifier'])):return ['invalid classifier'+FIX]
   expected=a['group'].replace('.','/')+'/'+a['module']+'/'+a['version']+'/'+a['name']+'-'+a['version']+('-'+a['classifier'] if a['classifier'] else '')+'.'+a['ext']
   if a.get('path')!=expected or expected in paths:return ['ambiguous artifact path'+FIX]
   paths.add(expected)
   if not re.fullmatch(r'https?://[^/@\s]+/[^\s]*',a.get('url','')) or not re.fullmatch(r'sha256-[A-Za-z0-9+/]{43}=',a.get('hash','')):return ['invalid artifact origin or hash'+FIX]
  if not all(isinstance(data.get(k),str) for k in ('antVersion','ivyVersion','javaVersion','resolveTarget','ivyFile','buildFile')):return ['missing native toolchain or target metadata'+FIX]
  return []
 except (OSError,ValueError,TypeError,KeyError,ET.ParseError) as error:return [str(error)+FIX]
