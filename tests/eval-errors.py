#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import copy,json,shutil,subprocess,sys,tempfile
from pathlib import Path
REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO))
from ant_purifier import lock
with tempfile.TemporaryDirectory(prefix='ant-invalid-') as tmp:
 root=Path(tmp)/'project';shutil.copytree(REPO/'examples/minimal',root,ignore=shutil.ignore_patterns('build','.ant-purifier','.classpath','.project'))
 sidecar=root/'ant-purifier.lock.json';original=sidecar.read_text();data=json.loads(original)
 expression='let f = builtins.getFlake '+json.dumps(str(REPO))+'; in (f.lib.ant-purifier.readLock { src = /. + '+json.dumps(str(root))+'; }).problems'
 def evaluate(invalid):
  result=subprocess.run(['nix','eval','--impure','--json','--expr',expression],text=True,capture_output=True)
  if result.returncode:assert invalid and 'ant-purifier' in result.stderr,result.stderr
  else:assert bool(json.loads(result.stdout))==invalid,result.stdout
 evaluate(False)
 native=root/'ivy.lock.xml';native_original=native.read_text();properties=root/'build.properties';properties_original=properties.read_text()
 for mutation in ('hash','artifact','metadata','source-roots','scalar','native-pin','configuration','malformed'):
  changed=copy.deepcopy(data);sidecar.write_text(original)
  if mutation=='hash':changed['contentHash']='bad'
  elif mutation=='artifact':del changed['artifacts'][0]['hash'];changed=lock.seal(changed)
  elif mutation=='metadata':changed['metadata'][0]['url']='https://user:password@example.invalid/artifact';changed=lock.seal(changed)
  elif mutation=='source-roots':changed['sourceRoots']=['../outside'];changed=lock.seal(changed)
  elif mutation=='scalar':changed=3
  elif mutation=='native-pin':native.write_text(native_original.replace('rev="3.17.0"','rev="0.0"'));changed['nativeHash']=lock.digest(native);changed=lock.seal(changed)
  elif mutation=='configuration':properties.write_text(properties_original+'\n# changed\n')
  if mutation=='malformed':sidecar.write_text('invalid JSON')
  else:sidecar.write_text(json.dumps(changed))
  evaluate(True);native.write_text(native_original);properties.write_text(properties_original)
 sidecar.unlink();evaluate(True)
print('PASS invalid-lock evaluation')
