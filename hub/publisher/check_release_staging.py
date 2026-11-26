#!/usr/bin/env python3
"""List staged release paths and flag files that need review."""

import argparse
import json
from pathlib import Path
import re
import stat
from addon_maintenance_policy import is_excluded_spreadsheet_payload

PRIVATE_KEY_HEADER = re.compile(rb'^-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\r?$', re.MULTILINE)
PRIVATE_KEY_NAMES = {'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519'}


def iter_staging_tree(source):
    source_stat = source.lstat()
    if not stat.S_ISDIR(source_stat.st_mode):
        raise ValueError('source must be a local directory')

    def walk(path, path_stat):
        yield path, path_stat
        if stat.S_ISDIR(path_stat.st_mode):
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                yield from walk(child, child.lstat())

    yield from walk(source, source_stat)


def staged_file_mode(path_stat):
    return 0o755 if path_stat.st_mode & 0o111 else 0o644


def check_staging(source):
    entries = []
    for path, path_stat in iter_staging_tree(source):
        mode = path_stat.st_mode
        relative_path = path.relative_to(source)
        relative = relative_path.as_posix()
        name = path.name.lower()
        findings = []
        entry = {'path': relative, 'findings': findings}
        if is_excluded_spreadsheet_payload(relative):
            findings.append('excluded spreadsheet addon payload')
        if path != source and '\\' in relative:
            findings.append('path contains a backslash')
        if '.git' in relative_path.parts:
            findings.append('Git metadata')
        if path != source and (name == '_config.php' or (
            (name == '.env' or name.startswith('.env.'))
            and not name.endswith(('.example', '.sample', '.template', '.dist'))
        )):
            findings.append('possible local deployment configuration')
        if stat.S_ISDIR(mode):
            entry.update(type='directory', mode='0755')
        elif stat.S_ISREG(mode):
            entry.update(type='file', mode=format(staged_file_mode(path_stat), '04o'), bytes=path_stat.st_size)
            with path.open('rb') as stream:
                has_private_key_header = PRIVATE_KEY_HEADER.search(stream.read(8192)) is not None
            if (name in PRIVATE_KEY_NAMES or (name.startswith('ssh_host_') and name.endswith('_key'))
                    or path.suffix.lower() in {'.key', '.p12', '.pfx', '.seed'} or has_private_key_header):
                findings.append('possible private key or key container')
        else:
            entry.update(type='unsupported')
            findings.append('symlink or special file cannot be packaged')
        entries.append(entry)
    if not any(entry['type'] == 'file' for entry in entries):
        entries[0]['findings'].append('source tree contains no regular files')
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        entries = check_staging(args.source_dir)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'{parser.prog}: {exc}\n')
    print(json.dumps(entries, indent=2))
    return int(any(entry['findings'] for entry in entries))


if __name__ == '__main__':
    raise SystemExit(main())

