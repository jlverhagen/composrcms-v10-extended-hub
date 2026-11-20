#!/usr/bin/env python3
"""Compare trusted locally generated Composr installer payloads and integrity metadata.

The generated quick-index PHP declaration is executed. Use only reviewed local builds.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import zipfile
import zlib

from catalogue_enforcement import GUARDED_FILES, render_checksums


def validate_names(names):
    if len(names) != len(set(names)):
        raise ValueError('Duplicate archive member')
    for name in names:
        path = PurePosixPath(name)
        if (not path.parts or path.is_absolute() or '..' in path.parts
                or str(path) != name or '\\' in name):
            raise ValueError(f'Unsafe archive member: {name}')
        if (path.parts[0] in {'tracker', 'aps', 'mobiquo', '.git'}
                or name == '_config.php' or 'composr_homesite_support_credits' in name):
            raise ValueError(f'Excluded release member: {name}')


def tar_payload(source):
    with tarfile.open(fileobj=source, mode='r:*') as archive:
        members = archive.getmembers()
        validate_names([member.name for member in members])
        if any(not member.isfile() for member in members):
            raise ValueError('Expected regular TAR members only')
        return {member.name: archive.extractfile(member).read() for member in members}


def zip_payload(path):
    with zipfile.ZipFile(path) as archive:
        validate_names(archive.namelist())
        return {name: archive.read(name) for name in archive.namelist()}


def verify(directory, version, php='php'):
    paths = {kind: directory / name for kind, name in {
        'upgrader': f'composr_upgrader-{version}.cms',
        'manual': f'composr_manualextraction_installer-{version}.zip',
        'quick': f'composr_quick_installer-{version}.zip',
        'source': f'composr-{version}.tar.gz',
        'guard': f'catalogue-enforcement-{version}.sha256',
    }.items()}
    sums = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name in sums or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid or duplicate SHA256SUMS entry')
        sums[name] = digest
    if set(sums) != {path.name for path in paths.values()}:
        raise ValueError('Unexpected SHA256SUMS inventory')
    for path in paths.values():
        if hashlib.sha256(path.read_bytes()).hexdigest() != sums[path.name]:
            raise ValueError(f'SHA256 mismatch: {path.name}')
    with paths['upgrader'].open('rb') as stream:
        core = tar_payload(stream)
    manual = zip_payload(paths['manual'])
    if set(manual) != set(core) | {'install.php'}:
        raise ValueError('Manual installer inventory mismatch')
    if any(manual[name] != data for name, data in core.items()):
        raise ValueError('Manual installer payload mismatch')
    quick = zip_payload(paths['quick'])
    if set(quick) != {'data.cms', 'install.php', 'readme.txt'}:
        raise ValueError('Quick installer inventory mismatch')
    if tar_payload(io.BytesIO(quick['data.cms'])) != core:
        raise ValueError('Quick installer payload mismatch')
    # Execute only the generated index prefix, never the stock installer.
    prefix, separator, stock = quick['install.php'].partition(b'?>')
    if not separator or b'list($QUICK_INDEX, $FILE_ARRAY, $DIR_ARRAY)' not in prefix:
        raise ValueError('Missing quick installer index')
    if stock != manual['install.php']:
        raise ValueError('Quick stock installer mismatch')
    declaration = prefix.partition(b'$DATADOTCMS_FILE =')[0]
    index = json.loads(subprocess.check_output([php], input=declaration +
        b'; echo json_encode([$QUICK_INDEX, $FILE_ARRAY, $DIR_ARRAY], JSON_THROW_ON_ERROR);'))
    locations, ordered, directories = index
    expected_dirs = sorted({str(parent) for name in core for parent in PurePosixPath(name).parents
                            if str(parent) != '.'})
    if set(locations) != set(core) or ordered != sorted(core) or directories != expected_dirs:
        raise ValueError('Quick installer index inventory mismatch')
    for name, (offset, length) in locations.items():
        if length != len(core[name]) or quick['data.cms'][offset:offset + length] != core[name]:
            raise ValueError(f'Quick installer index offset mismatch: {name}')
    with paths['source'].open('rb') as stream:
        source = tar_payload(stream)
    if set(source) != set(manual) | {'readme.txt', 'install.sql', '_config.php.template'}:
        raise ValueError('Source archive inventory mismatch')
    if any(source[name] != data for name, data in manual.items()):
        raise ValueError('Source archive payload mismatch')
    if source['readme.txt'] != quick['readme.txt']:
        raise ValueError('Installer README mismatch')
    # Decode the regenerated checksum map without loading application code.
    checksums = json.loads(subprocess.check_output([php, '-r',
        "echo json_encode(unserialize(stream_get_contents(STDIN), ['allowed_classes'=>false]), JSON_THROW_ON_ERROR);"],
        input=core['data/files.bin']))
    if set(checksums) != set(core) - {'data/files.bin'}:
        raise ValueError('Integrity inventory mismatch')
    for name, data in core.items():
        if name == 'data/files.bin':
            continue
        if name == 'sources/version.php':
            data = re.sub(rb'\d{10}', b'', data)
        digest = str(zlib.crc32(re.sub(rb'[\r\n\t ]', b'', data)))
        if checksums[name] != [digest]:
            raise ValueError(f'Integrity CRC mismatch: {name}')
    guard = render_checksums({name: hashlib.sha256(core[name]).hexdigest() for name in GUARDED_FILES})
    if paths['guard'].read_text() != guard:
        raise ValueError('Enforcement checksum mismatch')
    if f"return '{version}';".encode() not in core['sources_custom/extended_version.php']:
        raise ValueError('Extended version stamp mismatch')
    return {'version': version, 'core_payload_files': len(core), 'integrity_entries': len(checksums),
            'guarded_files': len(GUARDED_FILES), 'archive_sha256': sums,
            'checks': ['excluded paths', 'SHA256SUMS', 'matching four-format payloads',
                       'quick installer index offsets', 'integrity inventory and CRCs',
                       'enforcement checksums', 'Extended version stamp'],
            'limitation': 'Archive consistency only; installer execution and CMS workflows are not tested'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--php', default='php')
    args = parser.parse_args()
    print(json.dumps(verify(args.package_dir, args.version, args.php), indent=2))
