# SPDX-License-Identifier: MIT
"""Prepare a normal Eclipse/JDT classpath while retaining the user's settings."""
import fcntl,hashlib,json,os,re,tempfile,xml.etree.ElementTree as ET
from pathlib import Path
from . import lock
MARKER='org.nixpurifiers.ant'
def digest(text):return hashlib.sha256(text.encode()).hexdigest()
def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as stream:stream.write(text);temporary=Path(stream.name)
 temporary.replace(path)
def serialize(tree):ET.indent(tree,space='  ');return ET.tostring(tree,encoding='unicode')+'\n'
def owned(entry):return any(a.get('name')==MARKER for a in entry.findall('./attributes/attribute'))
def tag(entry):ET.SubElement(ET.SubElement(entry,'attributes'),'attribute',{'name':MARKER,'value':'managed'})
def source_roots(root):
 result=set()
 for directory,dirs,files in os.walk(root):
  dirs[:]=[d for d in dirs if d not in lock.IGNORED]
  for name in files:
   if not name.endswith('.java'):continue
   path=Path(directory)/name
   text=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(errors='replace'),flags=re.S)
   package=re.search(r'(?m)^\s*package\s+([\w$.]+)\s*;',text)
   directory_path=path.parent
   if package:
    segments=package.group(1).split('.')
    if tuple(directory_path.parts[-len(segments):])!=tuple(segments):continue
    for _ in segments:directory_path=directory_path.parent
   result.add(directory_path.relative_to(root).as_posix())
 return sorted(result) or (['src'] if (root/'src').exists() else ['.'])
def baseline_classpath(current,previous):
 if not previous:return current
 if current is not None and digest(current)==previous['afterHash']:return previous['before']
 if current is None:return None
 tree=ET.fromstring(current)
 for entry in list(tree):
  if owned(entry):tree.remove(entry)
 original=ET.fromstring(previous['before']) if previous['before'] else ET.Element('classpath')
 for entry in original:
  if entry.get('kind')=='con' and entry.get('path','').startswith('org.apache.ivyde.'):
   if not any(e.get('path')==entry.get('path') for e in tree):tree.append(entry)
 return serialize(tree)
def prepare(root,environment):
 cache=root/'.ant-purifier';cache.mkdir(exist_ok=True)
 with (cache/'editor.lock').open('a') as stream:
  fcntl.flock(stream,fcntl.LOCK_EX)
  state_path=cache/'editor.json';state=json.loads(state_path.read_text()) if state_path.exists() else {}
  classpath=root/'.classpath';current=classpath.read_text() if classpath.exists() else None
  before=baseline_classpath(current,state.get('classpath'))
  tree=ET.fromstring(before) if before else ET.Element('classpath')
  for entry in list(tree):
   if entry.get('kind')=='con' and entry.get('path','').startswith('org.apache.ivyde.'):tree.remove(entry)
  metadata=json.loads((environment/'metadata.json').read_text())
  inferred=source_roots(root);sources=set()
  for declared in metadata.get('sourceRoots',[]) or inferred:
   matching=[p for p in inferred if declared=='.' or p==declared or p.startswith(declared+'/')]
   sources.update(matching or [declared])
  if not any(e.get('kind')=='src' for e in tree):
   for path in sorted(sources):tag(ET.SubElement(tree,'classpathentry',{'kind':'src','path':'' if path=='.' else path}))
  if not any(e.get('kind')=='con' and e.get('path','').startswith('org.eclipse.jdt.launching.JRE_CONTAINER') for e in tree):tag(ET.SubElement(tree,'classpathentry',{'kind':'con','path':'org.eclipse.jdt.launching.JRE_CONTAINER'}))
  metadata=json.loads((environment/'metadata.json').read_text())
  for library in metadata.get('libraries',[{'path':p,'source':None} for p in metadata['classpath']]):
   jar=str(Path(library['path']).resolve())
   if not any(e.get('kind')=='lib' and e.get('path')==jar for e in tree):
    attributes={'kind':'lib','path':jar}
    if library.get('source'):attributes['sourcepath']=str(Path(library['source']).resolve())
    tag(ET.SubElement(tree,'classpathentry',attributes))
  if not any(e.get('kind')=='output' for e in tree):tag(ET.SubElement(tree,'classpathentry',{'kind':'output','path':'build/classes'}))
  after=serialize(tree);write(classpath,after);state['classpath']={'before':before,'afterHash':digest(after)}
  project=root/'.project';current=project.read_text() if project.exists() else None
  previous=state.get('project')
  before=previous['before'] if previous and current is not None and digest(current)==previous['afterHash'] else current
  tree=ET.fromstring(before) if before else ET.Element('projectDescription')
  if tree.find('name') is None:ET.SubElement(tree,'name').text=root.name
  natures=tree.find('natures')
  if natures is None:natures=ET.SubElement(tree,'natures')
  if not any(e.text=='org.eclipse.jdt.core.javanature' for e in natures):ET.SubElement(natures,'nature').text='org.eclipse.jdt.core.javanature'
  builders=tree.find('buildSpec')
  if builders is None:builders=ET.SubElement(tree,'buildSpec')
  if not any(e.findtext('name')=='org.eclipse.jdt.core.javabuilder' for e in builders):
   builder=ET.SubElement(builders,'buildCommand');ET.SubElement(builder,'name').text='org.eclipse.jdt.core.javabuilder';ET.SubElement(builder,'arguments')
  after=serialize(tree);write(project,after);state['project']={'before':before,'afterHash':digest(after)}
  write(state_path,json.dumps(state,sort_keys=True,indent=2)+'\n')
def restore(root):
 cache=root/'.ant-purifier';state_path=cache/'editor.json'
 if not state_path.exists():return
 with (cache/'editor.lock').open('a') as stream:
  fcntl.flock(stream,fcntl.LOCK_EX);state=json.loads(state_path.read_text())
  for name in ('classpath','project'):
   path=root/('.'+name);record=state.get(name)
   if not record or not path.exists():continue
   current=path.read_text()
   if digest(current)==record['afterHash']:
    if record['before'] is None:path.unlink()
    else:write(path,record['before'])
   elif name=='classpath':write(path,baseline_classpath(current,record))
  state_path.unlink()

def worker_cache(workspace):
 """Keep unrelated Buildship version discovery offline in this Ant worker."""
 cache=workspace/'cache';versions=cache/'tooling/gradle/versions.json'
 write(versions,'[]\n')
 return {'XDG_CACHE_HOME':str(cache)}
