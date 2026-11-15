#!/usr/bin/env python3
"""Reissue an approved catalogue against unchanged local addon TARs."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from build_catalogue import (
    CatalogueError,
    encode_catalogue,
    validate_catalogue,
    validate_entry,
)


def renew(previous_path, approved_sha256, package_root, private_key, key_id, output, days):
    previous_bytes = previous_path.read_bytes()
    if hashlib.sha256(previous_bytes).hexdigest() != approved_sha256:
        raise CatalogueError('previous catalogue does not match the approved digest')
    previous = json.loads(previous_bytes)
    now = int(time.time())
    # Validate the previous schema at its issuance time so expired catalogues can be renewed.
    validate_catalogue(previous, previous['source_id'], previous['issued_at'])
    if now <= previous['issued_at']:
        raise CatalogueError('renewal must be issued after the previous catalogue')
    if not 1 <= days <= 30 or not key_id or len(key_id) > 128:
        raise CatalogueError('invalid validity period or key ID')
    if private_key.is_symlink() or not private_key.is_file() or stat.S_IMODE(private_key.stat().st_mode) & 0o077:
        raise CatalogueError('signing key must be a private regular file with no group or other access')

    for entry in previous['addons']:
        filename = Path(urlsplit(entry['download_url']).path).name
        checked = validate_entry({**entry, 'package_file': filename}, package_root)
        if checked['sha256'] != entry['sha256']:
            raise CatalogueError(f"package digest changed for {entry['id']}")

    payload = encode_catalogue(validate_catalogue({
        **previous, 'issued_at': now, 'expires_at': now + days * 86400,
    }, previous['source_id'], now))
    output.mkdir(mode=0o700, exist_ok=False)
    try:
        manifest = output / 'catalogue.json'
        manifest.write_bytes(payload)
        signature = subprocess.check_output([
            'openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(private_key),
            '-in', str(manifest),
        ])
        if len(signature) != 64:
            raise CatalogueError('expected an Ed25519 signature')
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp) / 'signer.pub'
            raw_signature = Path(tmp) / 'signature'
            raw_signature.write_bytes(signature)
            subprocess.run([
                'openssl', 'pkey', '-in', str(private_key), '-pubout', '-out', str(public),
            ], check=True, stdout=subprocess.DEVNULL)
            subprocess.run([
                'openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', str(public),
                '-in', str(manifest), '-sigfile', str(raw_signature),
            ], check=True, stdout=subprocess.DEVNULL)
        (output / 'catalogue.sig.json').write_text(json.dumps({
            'algorithm': 'Ed25519', 'key_id': key_id,
            'signature': base64.b64encode(signature).decode('ascii'),
        }, sort_keys=True) + '\n', encoding='utf-8')
    except BaseException:
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'package-root', 'private-key', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--approved-sha256', required=True)
    parser.add_argument('--key-id', required=True)
    parser.add_argument('--days', type=int, default=7)
    args = parser.parse_args()
    try:
        renew(args.previous, args.approved_sha256, args.package_root,
              args.private_key, args.key_id, args.output, args.days)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')
    print('Verified renewal staged in', args.output)


if __name__ == '__main__':
    main()
