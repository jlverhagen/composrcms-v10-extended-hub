#!/usr/bin/env python3
"""Verify a local core release against a separately pinned Ed25519 public key."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import tarfile
import zlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from build_release_manifest import DISTRIBUTION_ID, validate_release_metadata, validate_version

DIGEST = re.compile(r'[0-9a-f]{64}')


def decode_json(raw):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON field: {key}')
            result[key] = value
        return result

    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)


def read_limited(path, max_bytes):
    with path.open('rb') as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f'file exceeds size limit: {path}')
    return raw


def verify_signature(raw, signature_path, public_key_path, expected_key_id):
    signature = decode_json(read_limited(signature_path, 4096))
    if (not isinstance(signature, dict) or set(signature) != {'algorithm', 'key_id', 'signature'}
            or signature['algorithm'] != 'Ed25519'
            or signature['key_id'] != expected_key_id or not isinstance(signature['signature'], str)):
        raise ValueError('unexpected signature envelope or core signing key ID')
    key_bytes = base64.b64decode(read_limited(public_key_path, 1024).strip(), validate=True)
    signature_bytes = base64.b64decode(signature['signature'], validate=True)
    key = Ed25519PublicKey.from_public_bytes(key_bytes)
    try:
        key.verify(signature_bytes, raw)
    except InvalidSignature as exc:
        raise ValueError('core release signature verification failed') from exc


def select_release(manifest, version):
    if (not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'distribution_id', 'releases'}
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
            or manifest['distribution_id'] != DISTRIBUTION_ID or not isinstance(manifest['releases'], list)):
        raise ValueError('invalid core release manifest')
    versions = {}
    for release in manifest['releases']:
        fields = {'version', 'upstream_base', 'upstream_commit', 'download_url', 'sha256'}
        if (not isinstance(release, dict) or set(release) != fields
                or not all(isinstance(value, str) for value in release.values())
                or not DIGEST.fullmatch(release['sha256'])):
            raise ValueError('invalid release entry')
        validate_release_metadata(release['version'], release['upstream_base'],
                                  release['upstream_commit'], release['download_url'])
        if release['version'] in versions:
            raise ValueError('duplicate version in core release manifest')
        versions[release['version']] = release
    if version not in versions:
        raise ValueError('requested release version is missing from the signed manifest')
    return versions[version]


def verify_inventory(stream, inventory, version, archive_digest, archive_size):
    root = f'composr-v10-extended-{version}'
    expected_archive = {'name': root + '.tar.gz', 'bytes': archive_size, 'sha256': archive_digest}
    if (not isinstance(inventory, dict) or set(inventory) != {'schema_version', 'distribution_id', 'version', 'archive', 'files'}
            or type(inventory['schema_version']) is not int or inventory['schema_version'] != 1
            or inventory['distribution_id'] != DISTRIBUTION_ID or inventory['version'] != version
            or inventory['archive'] != expected_archive or not isinstance(inventory['files'], list)):
        raise ValueError('inventory does not identify the verified archive')
    remaining = {}
    for entry in inventory['files']:
        if (not isinstance(entry, dict) or set(entry) != {'path', 'mode', 'bytes', 'sha256'}
                or not isinstance(entry['path'], str) or type(entry['bytes']) is not int
                or entry['path'] in remaining):
            raise ValueError('invalid or duplicate inventory entry')
        remaining[entry['path']] = entry
    count = len(remaining)
    if not count:
        raise ValueError('inventory contains no files')

    seen = set()
    directories = set()
    with tarfile.open(fileobj=stream, mode='r|gz') as archive:
        for member in archive:
            name = member.name
            parts = name.split('/')
            if (parts[0] != root or any(part in ('', '.', '..') for part in parts)
                    or '\\' in name or '\0' in name or name in seen
                    or (len(parts) > 1 and '/'.join(parts[:-1]) not in directories)):
                raise ValueError(f'unexpected or duplicate archive path: {name!r}')
            seen.add(name)
            if member.isdir():
                directories.add(name)
                continue
            if name == root or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.sparse is not None:
                raise ValueError(f'unexpected archive member type: {name!r}')
            entry = remaining.pop(name, None)
            if entry is None or entry['bytes'] != member.size or entry['mode'] != format(member.mode, '04o'):
                raise ValueError(f'archive member metadata does not match inventory: {name!r}')
            with archive.extractfile(member) as member_stream:
                digest = hashlib.file_digest(member_stream, 'sha256').hexdigest()
            if digest != entry['sha256']:
                raise ValueError(f'archive member digest does not match inventory: {name!r}')
    if remaining:
        raise ValueError(f'inventoried files missing from archive: {len(remaining)}')
    return count


def verify_release(manifest, signature, public_key, key_id, version, archive, inventory):
    validate_version(version)
    raw = read_limited(manifest, 2 * 1024 * 1024)
    verify_signature(raw, signature, public_key, key_id)
    release = select_release(decode_json(raw), version)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != release['sha256']:
            raise ValueError('archive SHA-256 does not match the signed release')
        archive_size = stream.seek(0, 2)
        stream.seek(0)
        count = verify_inventory(stream, decode_json(inventory.read_bytes()), version, digest, archive_size)
    return {'version': version, 'archive_sha256': digest, 'verified_files': count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--signature', required=True, type=Path)
    parser.add_argument('--public-key', required=True, type=Path, help='file containing the independently pinned base64 key')
    parser.add_argument('--key-id', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--inventory', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify_release(**vars(args)), sort_keys=True))
    except (OSError, EOFError, ValueError, tarfile.TarError, zlib.error) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
