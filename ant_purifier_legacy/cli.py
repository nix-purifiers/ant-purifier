# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from ant_purifier import lock as modern
from ant_purifier.cli import property_hashes, project_from_args, sri, write
from . import lock


def run(command, **options):
    return subprocess.run(list(map(str, command)), check=True, **options)


def context():
    value = lock.read(os.environ['ANT_PURIFIER_LEGACY_CONTEXT'])
    lock.validate_context(value)
    return value


def properties(extra):
    values = [token[2:] for token in shlex.split(os.environ.get('ANT_ARGS', '')) if token.startswith('-D')]+list(extra)
    result = property_hashes(values)
    if len({item['name'] for item in result}) != len(result):
        raise ValueError('legacy-basic-v1 requires unambiguous native property names')
    return values, sorted(result, key=lambda item: item['name'])


def observation_file(directory, observed):
    def escaped(value):
        for old, new in [('\\', '\\\\'), ('\n', '\\n'), ('\r', '\\r'), ('\t', '\\t'),
                         ('=', '\\='), (':', '\\:'), ('#', '\\#'), ('!', '\\!'), (' ', '\\ ')]:
            value = value.replace(old, new)
        return value
    directory.mkdir(parents=True, exist_ok=True)
    file = directory/'captured.properties'
    write(file, ''.join(escaped(key)+'='+escaped(observed[key])+'\n' for key in sorted(observed)))
    return file


def validate_manager_selection(expected):
    selected = os.environ.get('JAVACMD')
    if selected:
        executable = selected if Path(selected).is_absolute() else shutil.which(selected)
        if not executable or Path(executable).resolve() != Path(expected['manager']['executable']).resolve():
            raise ValueError('native JAVACMD differs from the source-owned legacy manager')


def capture(root, ivy, build, native, sidecar, target, extra, update=False, names=()):
    expected = context()
    validate_manager_selection(expected)
    values, fingerprints = properties(extra)
    previous = None
    if sidecar.exists():
        _, previous = lock.packet(sidecar)
    # An explicit legacy lock command always runs the original resolver target.
    # Pin retention is native Ivy mediation, not an up-to-date shortcut.
    selected = set()
    for name in names:
        if previous is None:
            raise ValueError('named legacy updates require an existing valid lock')
        matches = {modern.key(module) for module in previous['modules'] if name in (module['name'], modern.key(module))}
        if len(matches) != 1:
            raise ValueError('legacy update name is absent or ambiguous; use group:module')
        selected.update(matches)
    with tempfile.TemporaryDirectory(prefix='ant-legacy-capture-') as temporary:
        temp = Path(temporary)
        stage = temp/'project'
        shutil.copytree(root, stage, ignore=shutil.ignore_patterns(*modern.IGNORED))
        staged_ivy, staged_build = stage/ivy.relative_to(root), stage/build.relative_to(root)
        prior = temp/'previous.xml'
        if native.exists():
            modern.pins(native)
            shutil.copyfile(native, prior)
        output = temp/'resolution'
        output.mkdir()
        env = dict(os.environ, XDG_CACHE_HOME=str(temp/'cache'))
        env.pop('ANT_PURIFIER_LEGACY_CAPTURED', None)
        command = [os.environ['ANT_PURIFIER_JAVA'], *shlex.split(os.environ.get('ANT_OPTS', '')),
                   '-Djava.io.tmpdir='+str(temp), '-Duser.home='+str(temp/'native-user-home'),
                   '-Dant.home='+os.environ['ANT_PURIFIER_ANT_HOME'], '-cp', os.environ['ANT_PURIFIER_LOCK_CLASSPATH'],
                   'org.nixpurifiers.ant.legacy.NativeResolve', staged_ivy, output, prior,
                   'all' if update and not names else 'selected' if update else 'none', ','.join(sorted(selected)),
                   ','.join(modern.key(module) for module in previous['modules']) if previous else ','.join(modern.pins(prior)) if prior.exists() else '',
                   staged_build, target, *values]
        run(command, cwd=stage, env=env, stdout=sys.stderr)
        resolution = ET.parse(output/'resolution.xml').getroot()
        observed = dict(resolution.find('runtime').attrib)
        modules, artifacts = [], []
        for record in resolution.findall('./modules/module'):
            module = {key: record.get(key) for key in ('group', 'name', 'version')}
            module['descriptor'] = Path(record.get('file')).read_text()
            origin = record.find('original')
            if origin is None:
                raise ValueError('missing native legacy module origin')
            module['original'] = {'url': origin.get('url'), 'hash': sri(origin.get('file'))}
            old = next((item for item in (previous or {}).get('modules', [])
                        if all(item[key] == module[key] for key in ('group', 'name', 'version'))), None)
            updating = update and (not names or modern.key(module) in selected)
            if old and old.get('original') and old['original']['hash'] != module['original']['hash'] and not updating:
                raise ValueError('pinned native legacy module changed bytes; use explicit update')
            if old and old.get('original', {}).get('hash') == module['original']['hash']:
                module['descriptor'] = old['descriptor']
            modules.append(module)
        unique = {}
        for record in resolution.findall('./artifacts/artifact'):
            artifact = {key: value for key, value in record.attrib.items() if key != 'file'}
            artifact['hash'] = sri(record.get('file'))
            old = next((item for item in (previous or {}).get('artifacts', [])
                        if all(item[key] == artifact[key] for key in ('group', 'module', 'version', 'name', 'ext', 'classifier'))), None)
            if old and old['hash'] != artifact['hash'] and not (update and (not names or artifact['group']+':'+artifact['module'] in selected)):
                raise ValueError('pinned native legacy artifact changed bytes; use explicit update')
            collision = unique.get(artifact['path'])
            if collision and collision['hash'] != artifact['hash']:
                raise ValueError('native legacy artifacts collide')
            if not collision or (artifact['type'], artifact['url']) < (collision['type'], collision['url']):
                unique[artifact['path']] = artifact
        artifacts = list(unique.values())
        staged_native = output/'ivy.lock.xml'
        payload = modern.seal(dict(version=1, antVersion=observed['antVersion'], ivyVersion=observed['ivyVersion'],
            javaVersion=observed['javaVersion'], resolverVersion=expected['collector']['version'],
            nativeHash=modern.digest(staged_native), ivyHash=modern.digest(ivy), buildHash=modern.digest(build),
            inputs=modern.inputs(root, native), ivyFile=ivy.relative_to(root).as_posix(),
            buildFile=build.relative_to(root).as_posix(), resolveTarget=target, properties=fingerprints,
            modules=sorted(modules, key=modern.key), artifacts=sorted(artifacts, key=lambda item: item['path']),
            metadata=[], sourceRoots=sorted({item.get('path') for item in resolution.findall('./sourceRoots/source')})))
        problems = modern.problems(root, staged_native, payload, input_native=native, ivy=ivy, build=build)
        if problems:
            raise ValueError('\n'.join(problems))
        serialized = json.dumps(payload, sort_keys=True, indent=2)+'\n'
        outer = modern.seal(dict(version=2, profile=lock.PROFILE, payloadFile=lock.payload_file(sidecar).name,
            payloadHash=hashlib.sha256(serialized.encode()).hexdigest(), runtimeContext=expected,
            runtimeHash=lock.digest(expected), observed=observed))
        # Publish no partial companion if native collection or graph validation failed.
        write(native, staged_native.read_text())
        write(lock.payload_file(sidecar), serialized)
        write(sidecar, json.dumps(outer, sort_keys=True, indent=2)+'\n')
    lock.checked(root, native, sidecar, ivy, build, expected)
    print('Locked native legacy Ivy graph', file=sys.stderr)


def prefetch(root, ivy, build, native, sidecar):
    expected = context()
    validate_manager_selection(expected)
    outer, payload = lock.checked(root, native, sidecar, ivy, build, expected)
    cache = sidecar.parent/'.ant-purifier'/hashlib.sha256(str(sidecar).encode()).hexdigest()[:12]
    cache = cache/outer['runtimeHash'][:16]
    cache.mkdir(parents=True, exist_ok=True)
    observation = observation_file(cache, outer['observed'])
    env = dict(os.environ, ANT_PURIFIER_LEGACY_CAPTURED=str(observation))
    run([os.environ['ANT_PURIFIER_JAVA'], *shlex.split(os.environ.get('ANT_OPTS', '')),
         '-cp', os.environ['ANT_PURIFIER_LOCK_CLASSPATH'], 'org.nixpurifiers.ant.legacy.Check'], cwd=root, env=env)
    command = ['nix', 'build', '--impure', '--file', os.environ['ANT_PURIFIER_REALIZE'],
               '--argstr', 'project', root, '--argstr', 'ivyFile', ivy, '--argstr', 'buildFile', build,
               '--argstr', 'ivyLock', native, '--argstr', 'lockFile', sidecar,
               '--no-link', '--print-out-paths']
    environment = Path(run(command, text=True, stdout=subprocess.PIPE).stdout.strip())
    run(['nix-store', '--add-root', cache/'environment', '--indirect', '--realise', environment], stdout=subprocess.DEVNULL)
    # This is the already-built caller-owned runtime, not a reconstructed SDK path from a lock.
    run(['nix-store', '--add-root', cache/'runtime', '--indirect', '--realise', os.environ['ANT_PURIFIER_LEGACY_RUNTIME']], stdout=subprocess.DEVNULL)
    return environment, payload, observation


def native_options(arguments):
    targets, values = [], []
    index = 0
    flags = {'-verbose', '-v', '-debug', '-d', '-quiet', '-q', '-emacs', '-noinput'}
    with_value = {'-f', '-file', '-buildfile', '-find', '-s', '-logfile', '-l'}
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith('-D'):
            values.append(argument[2:])
        elif argument in with_value:
            index += 1
            if index >= len(arguments):
                raise ValueError('missing legacy native option value')
        elif argument not in flags:
            if argument.startswith('-') or not argument or '\n' in argument:
                raise ValueError('native option is outside legacy-basic-v1: '+argument)
            targets.append(argument)
        index += 1
    return targets, values


def main():
    parser = argparse.ArgumentParser(description='Explicit legacy basic native Ant/Ivy workflow')
    parser.add_argument('--project')
    parser.add_argument('--ivy-file')
    parser.add_argument('--build-file')
    parser.add_argument('--native-lock')
    parser.add_argument('--lockfile')
    parser.add_argument('--resolve-target', default='resolve')
    parser.add_argument('-D', '--property', action='append', default=[])
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('lock')
    commands.add_parser('update').add_argument('names', nargs='*')
    commands.add_parser('prefetch').add_argument('--print-environment', action='store_true')
    commands.add_parser('native').add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.args[1:] if args.command == 'native' and args.args[:1] == ['--'] else args.args if args.command == 'native' else []
    root, build = project_from_args(arguments)
    if args.project:
        root = Path(args.project).expanduser().resolve()
        build = root/'build.xml'
    if args.build_file:
        build = Path(args.build_file).expanduser().resolve()
    ivy = Path(args.ivy_file).expanduser().resolve() if args.ivy_file else root/'ivy.xml'
    native = Path(args.native_lock).expanduser().resolve() if args.native_lock else root/'ivy.lock.xml'
    sidecar = Path(args.lockfile).expanduser().resolve() if args.lockfile else root/'ant-purifier.lock.json'
    if not ivy.is_relative_to(root) or not build.is_relative_to(root):
        raise ValueError('legacy-basic-v1 requires build and Ivy files in one native project')
    if args.command in ('lock', 'update'):
        capture(root, ivy, build, native, sidecar, args.resolve_target, args.property,
                args.command == 'update', getattr(args, 'names', ()))
    elif args.command == 'prefetch':
        print(prefetch(root, ivy, build, native, sidecar)[0])
    else:
        if arguments and all(value in ('-version', '-help', '-h') for value in arguments):
            ant = os.environ['ANT_PURIFIER_ANT']
            os.execv(ant, [ant, *arguments])
        targets, values = native_options(arguments)
        ambient_targets, _ = native_options(shlex.split(os.environ.get('ANT_ARGS', '')))
        targets = ambient_targets+targets
        _, fingerprints = properties(values)
        environment, payload, observation = prefetch(root, ivy, build, native, sidecar)
        if fingerprints != payload['properties']:
            raise ValueError('native properties differ from captured legacy configuration; run lock with the intended properties')
        os.environ.update(ANT_PURIFIER_ENVIRONMENT=str(environment), ANT_PURIFIER_IVY_FILE=str(ivy),
            ANT_PURIFIER_PROJECT_ROOT=str(root), ANT_PURIFIER_LEGACY_TARGETS='\n'.join(targets),
            ANT_PURIFIER_LEGACY_CAPTURED=str(observation))
        old_classpath = os.environ.get('CLASSPATH', '')
        os.environ['CLASSPATH'] = os.environ['ANT_PURIFIER_LOCK_CLASSPATH']+((':'+old_classpath) if old_classpath else '')
        ant = os.environ['ANT_PURIFIER_ANT']
        os.execv(ant, [ant, '-listener', 'org.nixpurifiers.ant.legacy.NativeReplay', *arguments])
