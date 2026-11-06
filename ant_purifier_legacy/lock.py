# SPDX-License-Identifier: MIT
"""Closed legacy dispatch around the unchanged native graph validator."""
import hashlib
import json
import os
from pathlib import Path
import re
from ant_purifier import lock as modern

PROFILE = 'legacy-basic-v1'
OUTER = {'version', 'profile', 'payloadFile', 'payloadHash', 'runtimeContext', 'runtimeHash', 'observed', 'contentHash'}
PAYLOAD = {'version', 'antVersion', 'ivyVersion', 'javaVersion', 'resolverVersion', 'nativeHash', 'ivyHash',
           'buildHash', 'inputs', 'ivyFile', 'buildFile', 'resolveTarget', 'properties', 'modules', 'artifacts',
           'metadata', 'sourceRoots', 'contentHash'}
OBSERVED = {'contextHash', 'sdkIdentity', 'managerIdentity', 'executable', 'runtimeHome', 'javaVersion',
            'antVersion', 'ivyVersion', 'antJar', 'ivyJar', 'collectorJar'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate legacy metadata field: '+key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs)


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('invalid closed legacy '+label)


def hash_value(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def store_path(value):
    prefix = os.environ.get('ANT_PURIFIER_STORE_DIR', '/nix/store')+'/'
    return (isinstance(value, str) and value.startswith(prefix)
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and all(part not in ('', '.', '..') for part in value[len(prefix):].split('/')))


def context_map(value):
    if not isinstance(value, dict) or not value:
        raise ValueError('missing legacy Nix context')
    for path, item in value.items():
        if not store_path(path) or not isinstance(item, dict) or not item or set(item)-{'path', 'allOutputs', 'outputs'}:
            raise ValueError('invalid legacy Nix context')
        if any(key in item and item[key] is not True for key in ('path', 'allOutputs')):
            raise ValueError('invalid legacy Nix path context')
        if 'outputs' in item and (not isinstance(item['outputs'], list) or not item['outputs']
                                  or not all(isinstance(name, str) and name for name in item['outputs'])):
            raise ValueError('invalid legacy Nix output context')


def validate_context(value):
    exact(value, {'version', 'sdk', 'sdkIdentityHash', 'manager', 'managerIdentityHash', 'contract', 'ant', 'ivy', 'collector'}, 'runtime context')
    if value['version'] != 'ant-legacy-runtime-context-v1':
        raise ValueError('unsupported legacy runtime context version')
    sdk, manager = value['sdk'], value['manager']
    exact(sdk, {'version', 'output', 'home', 'outputContext', 'homeContext'}, 'SDK identity')
    if sdk['version'] != 'sdk-output-home-context-v1' or not all(store_path(sdk[k]) for k in ('output', 'home')):
        raise ValueError('invalid legacy SDK identity')
    for key in ('outputContext', 'homeContext'):
        context_map(sdk[key])
    if value['sdkIdentityHash'] != digest(sdk):
        raise ValueError('legacy SDK identity hash differs')
    exact(manager, {'version', 'sdkIdentity', 'executable', 'runtimeHome', 'executableContext', 'runtimeHomeContext'}, 'manager identity')
    if (manager['version'] != 'jvm-manager-executable-runtime-home-v1'
            or manager['sdkIdentity'] != value['sdkIdentityHash']
            or not all(store_path(manager[k]) for k in ('executable', 'runtimeHome'))):
        raise ValueError('invalid mandatory legacy manager identity')
    for key in ('executableContext', 'runtimeHomeContext'):
        context_map(manager[key])
    if value['managerIdentityHash'] != digest(manager):
        raise ValueError('legacy manager identity hash differs')
    exact(value['contract'], {'source', 'sourceContext'}, 'SDK contract source')
    if not store_path(value['contract']['source']):
        raise ValueError('invalid legacy SDK contract source')
    context_map(value['contract']['sourceContext'])
    for label in ('ant', 'collector'):
        record = value[label]
        exact(record, {'output', 'outputContext', 'jar', 'jarContext', 'version'}, label+' origin')
        if not all(store_path(record[k]) for k in ('output', 'jar')) or not isinstance(record['version'], str) or not record['version']:
            raise ValueError('invalid legacy '+label+' origin')
        context_map(record['outputContext'])
        context_map(record['jarContext'])
    exact(value['ivy'], {'output', 'outputContext', 'version'}, 'Ivy origin')
    if not store_path(value['ivy']['output']) or not isinstance(value['ivy']['version'], str) or not value['ivy']['version']:
        raise ValueError('invalid legacy Ivy origin')
    context_map(value['ivy']['outputContext'])


def payload_file(sidecar):
    sidecar = Path(sidecar)
    return sidecar.with_name(sidecar.name+'.payload.json')


def packet(sidecar):
    sidecar = Path(sidecar)
    outer = read(sidecar)
    exact(outer, OUTER, 'companion')
    if type(outer['version']) is not int or outer['version'] != 2 or outer['profile'] != PROFILE:
        raise ValueError('unsupported legacy profile; modern locks are not implicitly upgraded')
    if outer['contentHash'] != modern.seal(outer)['contentHash']:
        raise ValueError('legacy contentHash mismatch')
    validate_context(outer['runtimeContext'])
    if outer['runtimeHash'] != digest(outer['runtimeContext']):
        raise ValueError('legacy runtime hash differs')
    file = payload_file(sidecar)
    if outer['payloadFile'] != file.name or outer['payloadHash'] != modern.digest(file):
        raise ValueError('legacy graph payload changed since capture')
    payload = read(file)
    exact(payload, PAYLOAD, 'graph payload')
    if payload['version'] != 1 or type(payload['version']) is not int or payload['contentHash'] != modern.seal(payload)['contentHash']:
        raise ValueError('invalid sealed legacy graph payload')
    if payload['metadata'] != []:
        raise ValueError('Maven projections are not part of legacy-basic-v1')
    observed = outer['observed']
    exact(observed, OBSERVED, 'native observation')
    if not all(isinstance(item, str) and item for item in observed.values()):
        raise ValueError('invalid native legacy observation')
    runtime = outer['runtimeContext']
    if (observed['contextHash'] != outer['runtimeHash'] or observed['sdkIdentity'] != runtime['sdkIdentityHash']
            or observed['managerIdentity'] != runtime['managerIdentityHash']
            or observed['antVersion'] != runtime['ant']['version'] or observed['ivyVersion'] != runtime['ivy']['version']):
        raise ValueError('native legacy observation is bound to another runtime')
    if not all(store_path(observed[k]) for k in ('executable', 'runtimeHome', 'antJar', 'ivyJar', 'collectorJar')):
        raise ValueError('invalid native legacy origin paths')
    if (payload['antVersion'] != runtime['ant']['version'] or payload['ivyVersion'] != runtime['ivy']['version']
            or payload['resolverVersion'] != runtime['collector']['version'] or payload['javaVersion'] != observed['javaVersion']):
        raise ValueError('legacy native toolchain metadata differs')
    if not isinstance(payload['properties'], list):
        raise ValueError('invalid legacy property fingerprints')
    for prop in payload['properties']:
        exact(prop, {'name', 'hash'}, 'property fingerprint')
        if not isinstance(prop['name'], str) or not prop['name'] or not hash_value(prop['hash']):
            raise ValueError('invalid legacy property fingerprint')
    return outer, payload


def checked(root, native, sidecar, ivy, build, expected):
    outer, payload = packet(sidecar)
    validate_context(expected)
    if outer['runtimeContext'] != expected:
        raise ValueError('legacy runtime/profile changed; run ant-purifier lock explicitly')
    problems = modern.problems(root, native, payload, ivy=ivy, build=build)
    if problems:
        raise ValueError('\n'.join(problems))
    observed = outer['observed']
    paths = {'executable': expected['manager']['executable'], 'runtimeHome': expected['manager']['runtimeHome'],
             'antJar': expected['ant']['jar'], 'ivyJar': expected['ivy']['output'], 'collectorJar': expected['collector']['jar']}
    if any(observed[key] != str(Path(value).resolve(strict=True)) for key, value in paths.items()):
        raise ValueError('recorded legacy native origin differs from the source-owned runtime')
    return outer, payload
