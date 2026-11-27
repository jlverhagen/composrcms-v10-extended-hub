#!/usr/bin/env python3
"""Package a staged source tree reproducibly without installing or publishing it."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import stat
import tarfile
import tempfile

from build_release_manifest import DISTRIBUTION_ID, sha256_file, validate_version
from check_release_staging import iter_staging_tree, staged_file_mode
from addon_maintenance_policy import is_excluded_spreadsheet_payload, is_excluded_nested_csv_payload


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def add_entry(archive, source, source_stat, archive_path):
    if stat.S_ISDIR(source_stat.st_mode):
        entry = tarfile.TarInfo(archive_path)
        entry.type = tarfile.DIRTYPE
        entry.mode = 0o755
        archive.addfile(entry)
        return None

    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError(f'source tree contains a non-regular file: {source}')
    entry = tarfile.TarInfo(archive_path)
    entry.size = source_stat.st_size
    entry.mode = staged_file_mode(source_stat)
    with source.open('rb') as stream:
        reader = HashingReader(stream)
        archive.addfile(entry, reader)
        if stream.read(1):
            raise ValueError(f'file grew while packaging: {source}')
    return {
        'path': archive_path,
        'bytes': entry.size,
        'mode': format(entry.mode, '04o'),
        'sha256': reader.digest.hexdigest(),
    }


def build_package(source, destination, version):
    validate_version(version)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('source must be a local directory')
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination already exists')
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('destination must be outside the source tree')

    prefix = f'composr-v10-extended-{version}'
    archive_name = prefix + '.tar.gz'
    files = []
    with tempfile.TemporaryDirectory(prefix='.release-', dir=destination.parent) as temp:
        staging = Path(temp)
        package = staging / archive_name
        with package.open('wb') as output:
            with gzip.GzipFile(filename='', fileobj=output, mode='wb', compresslevel=9, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                    for path, path_stat in iter_staging_tree(source):
                        relative = path.relative_to(source).as_posix()
                        if is_excluded_nested_csv_payload(relative):
                            raise ValueError(f"Excluded nested CSV addon payload: {relative}")
                        if is_excluded_spreadsheet_payload(relative):
                            raise ValueError(f'excluded spreadsheet addon payload: {relative}')
                        if '\\' in relative:
                            raise ValueError(f'unsupported path in source tree: {path}')
                        archive_path = prefix if path == source else f'{prefix}/{relative}'
                        record = add_entry(archive, path, path_stat, archive_path)
                        if record is not None:
                            files.append(record)
        if not files:
            raise ValueError('source tree contains no regular files')

        digest = sha256_file(package)
        inventory = {
            'schema_version': 1,
            'distribution_id': DISTRIBUTION_ID,
            'version': version,
            'archive': {'name': archive_name, 'bytes': package.stat().st_size, 'sha256': digest},
            'files': files,
        }
        inventory_path = staging / 'inventory.json'
        inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        inventory_digest = sha256_file(inventory_path)
        (staging / 'SHA256SUMS').write_text(
            f'{digest}  {archive_name}\n{inventory_digest}  inventory.json\n',
            encoding='utf-8', newline='\n',
        )
        staging.rename(destination)
    return destination / archive_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True, help='new directory under an existing parent')
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    try:
        print(build_package(args.source_dir, args.output_dir, args.version))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()

