# SPDX-License-Identifier: MIT
"""Prepare native Ivy selection without recording Nix artifacts as downloads."""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit


def properties(views, destination):
    import jvm_repository
    modules = jvm_repository.read_catalogs(views)
    entries = [(f'repository.{index}', Path(view['repository']).as_uri() + '/')
               for index, view in enumerate(views)]
    entries += [('module.' + group + ':' + name, module['version'])
                for (group, name), module in sorted(modules.items())]
    destination.write_text(''.join(key.replace(':', '\\:') + '=' + value + '\n' for key, value in entries))
    return modules


def supplied_origin(url, views):
    parsed = urlsplit(url or '')
    if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
        return False
    path = Path(unquote(parsed.path)).resolve()
    return any(path.is_relative_to(Path(view['repository']).resolve()) for view in views)


def unpin(native, declaration, modules):
    document = ET.parse(native)
    dependencies = document.getroot().find('dependencies')
    if dependencies is None:
        return
    source = ET.parse(declaration).getroot().find('dependencies')
    declared = {(node.get('org'), node.get('name')): node for node in source or [] if node.tag == 'dependency'}
    for node in list(dependencies):
        coordinate = (node.get('org'), node.get('module' if node.tag == 'override' else 'name'))
        if coordinate not in modules:
            continue
        if node.tag == 'override':
            dependencies.remove(node)
        elif node.tag == 'dependency' and coordinate in declared:
            for key in ('rev', 'revConstraint'):
                node.attrib.pop(key, None)
                if key in declared[coordinate].attrib:
                    node.set(key, declared[coordinate].get(key))
    document.write(native, encoding='unicode')


def prepare(environment, repository, catalog):
    modules = {(module['group'], module['name']): module
               for module in json.loads(catalog.read_text())['modules']}
    native = environment / 'ivy.lock.xml'
    document = ET.parse(native)
    dependencies = document.getroot().find('dependencies')
    if dependencies is None:
        dependencies = ET.SubElement(document.getroot(), 'dependencies')
    for node in list(dependencies):
        coordinate = (node.get('org'), node.get('module' if node.tag == 'override' else 'name'))
        if coordinate in modules:
            if node.tag == 'override':
                dependencies.remove(node)
            elif node.tag == 'dependency':
                node.set('rev', modules[coordinate]['version'])
                node.set('revConstraint', modules[coordinate]['version'])
    for (group, name), module in sorted(modules.items()):
        ET.SubElement(dependencies, 'override', {'org': group, 'module': name,
            'rev': module['version'], 'matcher': 'exact'})
    document.write(native, encoding='unicode')
    settings = ET.parse(environment / 'settings.xml')
    root = settings.getroot()
    chain = ET.SubElement(root.find('resolvers'), 'chain',
        {'name': 'nix-project-inputs', 'returnFirst': 'true'})
    ET.SubElement(chain, 'ibiblio', {'name': 'nix-provided', 'root': repository.as_uri() + '/',
        'm2compatible': 'true', 'usepoms': 'true'})
    ET.SubElement(chain, 'resolver', {'ref': root.find('settings').get('defaultResolver')})
    root.find('settings').set('defaultResolver', 'nix-project-inputs')
    settings.write(environment / 'settings.xml', encoding='unicode')
    metadata = environment / 'metadata.json'
    data = json.loads(metadata.read_text())
    for jar in sorted(repository.rglob('*.jar')):
        if jar.name.endswith(('-sources.jar', '-javadoc.jar')):
            continue
        source = jar.with_name(jar.stem + '-sources.jar')
        data['classpath'].append(str(jar))
        data['libraries'].append({'path': str(jar), 'source': str(source) if source.is_file() else None})
    metadata.write_text(json.dumps(data, sort_keys=True) + '\n')


if __name__ == '__main__':
    prepare(*map(Path, sys.argv[1:4]))
