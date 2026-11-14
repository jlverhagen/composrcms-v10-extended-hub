#!/usr/bin/env python3
"""Generate unsigned core release metadata from an existing local archive."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

DISTRIBUTION_ID = 'composrcms-v10-extended'
UPSTREAM_BASE_PATTERN = r'10\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
CALENDAR_VERSION_PATTERN = r'[1-9][0-9]{3}\.(?:0[1-9]|1[0-2])\.[1-9][0-9]*(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?'
LEGACY_VERSION_PATTERN = (
    UPSTREAM_BASE_PATTERN + r'-ext\.(?:0|[1-9][0-9]*)(?:-[a-z0-9]+(?:[.-][a-z0-9]+)*)?'
)


def validate_version(version):
    if not (re.fullmatch(CALENDAR_VERSION_PATTERN, version) or re.fullmatch(LEGACY_VERSION_PATTERN, version)):
        raise ValueError('expected an Extended release version such as 2026.11.1-alpha.1')


def sha256_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_release_metadata(version, upstream_base, upstream_commit, download_url):
    validate_version(version)
    if upstream_base != '10.0.52' or (re.fullmatch(LEGACY_VERSION_PATTERN, version) and not version.startswith(upstream_base + '-ext.')):
        raise ValueError('upstream baseline must match the Extended version')
    if not re.fullmatch(r'[0-9a-f]{40}', upstream_commit):
        raise ValueError('upstream commit must be a full lowercase Git SHA-1')
    if (not download_url.startswith('https://')
            or any(ord(char) <= 32 or ord(char) == 127 for char in download_url)
            or any(char in download_url for char in ('\\', '#', '?'))):
        raise ValueError('download URL must be an absolute HTTPS archive URL')
    url = urlsplit(download_url)
    if (not url.hostname or url.username is not None or url.password is not None
            or url.port == 0 or not url.path or url.path.endswith('/')):
        raise ValueError('download URL must name an HTTPS archive without credentials')


def build_manifest(archive, version, upstream_base, upstream_commit, download_url):
    validate_release_metadata(version, upstream_base, upstream_commit, download_url)
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size == 0:
        raise ValueError('archive must be a nonempty regular local file')

    return {
        'schema_version': 1,
        'distribution_id': DISTRIBUTION_ID,
        'releases': [{
            'version': version,
            'upstream_base': upstream_base,
            'upstream_commit': upstream_commit,
            'download_url': download_url,
            'sha256': sha256_file(archive),
        }],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--upstream-base', required=True)
    parser.add_argument('--upstream-commit', required=True)
    parser.add_argument('--download-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_manifest(args.archive, args.version, args.upstream_base,
                                  args.upstream_commit, args.download_url)
        with args.output.open('x', encoding='utf-8', newline='\n') as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write('\n')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
