#!/usr/bin/env python3
"""Offline, unsigned addon catalogue builder (NOT a release signer)."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import time
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
MAX_TAR_ENTRIES = 10000
TAR_BLOCK_SIZE = tarfile.BLOCKSIZE
ZERO_BLOCK = bytes(TAR_BLOCK_SIZE)
ID = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')
MAX_CATALOGUE_BYTES = 2 * 1024 * 1024
MAX_ADDONS = 2000
CATALOGUE_SCHEMA = Path(__file__).resolve().parents[1] / 'schemas' / 'addon-catalogue.schema.json'

class CatalogueError(ValueError):
    pass

def iter_tar_entries(stream):
    """Yield validated headers with the stream positioned at each entry body."""
    stream.seek(0, 2)
    size = stream.tell()
    if not size or size > MAX_ARCHIVE_BYTES or size % TAR_BLOCK_SIZE:
        raise CatalogueError('invalid tar size')
    stream.seek(0)

    entries = 0
    while stream.tell() < size:
        header = stream.read(TAR_BLOCK_SIZE)
        if header == ZERO_BLOCK:
            second = stream.read(TAR_BLOCK_SIZE)
            if len(second) != TAR_BLOCK_SIZE:
                raise CatalogueError('incomplete TAR end marker')
            if second != ZERO_BLOCK:
                raise CatalogueError('non-zero data after TAR end marker')
            for chunk in iter(lambda: stream.read(8192), b''):
                if chunk.strip(b'\0'):
                    raise CatalogueError('non-zero data after TAR end marker')
            return
        if len(header) != TAR_BLOCK_SIZE:
            raise CatalogueError('truncated TAR header')

        stored_checksum = header[148:156].strip(b' \0')
        if not re.fullmatch(rb'[0-7]+', stored_checksum):
            raise CatalogueError('invalid TAR checksum')
        checksum = sum(header[:148]) + 8 * ord(' ') + sum(header[156:])
        if checksum != int(stored_checksum, 8):
            raise CatalogueError('TAR header checksum mismatch')

        entry_type = header[156:157]
        if entry_type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE):
            raise CatalogueError('unsupported TAR entry type')
        name = header[:100].rstrip(b'\0')
        prefix = header[345:500].rstrip(b'\0')
        if prefix:
            if header[257:262] != b'ustar':
                raise CatalogueError('ambiguous TAR prefix')
            name = prefix + b'/' + name
        if (not name or name.startswith(b'/') or b'\\' in name or b'\0' in name
                or b'//' in name or re.match(rb'^[A-Za-z]:', name)
                or any(part in (b'.', b'..') for part in name.split(b'/'))):
            raise CatalogueError('unsafe TAR path')
        if (entry_type == tarfile.DIRTYPE) != name.endswith(b'/'):
            raise CatalogueError('ambiguous TAR entry type')

        size_field = header[124:136].strip(b' \0')
        if not re.fullmatch(rb'[0-7]+', size_field):
            raise CatalogueError('invalid TAR entry size')
        entry_size = int(size_field, 8)
        blocks = (entry_size + TAR_BLOCK_SIZE - 1) // TAR_BLOCK_SIZE
        next_header = stream.tell() + blocks * TAR_BLOCK_SIZE
        if next_header > size:
            raise CatalogueError('truncated TAR entry')
        entries += 1
        if entries > MAX_TAR_ENTRIES:
            raise CatalogueError('too many TAR entries')
        yield name, entry_type == tarfile.DIRTYPE, entry_size
        stream.seek(next_header)
    raise CatalogueError('missing TAR end marker')


def inspect_tar(path):
    if not path.is_file():
        raise CatalogueError('archive missing')
    names = set()
    files = set()
    directories = set()
    total = 0
    addon_inf = None
    try:
        with path.open('rb') as stream:
            for raw_name, is_directory, entry_size in iter_tar_entries(stream):
                name = raw_name.rstrip(b'/')
                if name in names:
                    raise CatalogueError('duplicate tar entry: ' + repr(name))
                parent, _, _ = name.rpartition(b'/')
                while parent:
                    if parent in files:
                        raise CatalogueError('tar file is also a directory: ' + repr(parent))
                    directories.add(parent)
                    parent, _, _ = parent.rpartition(b'/')
                if not is_directory and name in directories:
                    raise CatalogueError('tar file is also a directory: ' + repr(name))
                (directories if is_directory else files).add(name)
                names.add(name)
                total += entry_size
                if total > MAX_EXTRACTED_BYTES:
                    raise CatalogueError('uncompressed archive exceeds limit')
                if name == b'addon.inf' and not is_directory:
                    if entry_size > 65536:
                        raise CatalogueError('addon.inf exceeds limit')
                    content = stream.read(entry_size)
                    if len(content) != entry_size:
                        raise CatalogueError('truncated addon.inf')
                    addon_inf = content.decode('utf-8')
    except (UnicodeError, OSError) as exc:
        raise CatalogueError('invalid tar: ' + str(exc)) from exc
    if not addon_inf:
        raise CatalogueError('addon.inf missing or empty')
    return addon_inf

def validate_entry(entry, package_root):
    required = ('id','name','version','download_url','license','cms_compatibility','php_compatibility','package_file')
    if not isinstance(entry, dict) or any(k not in entry for k in required):
        raise CatalogueError('missing mandatory entry field')
    if not isinstance(entry['id'], str) or not ID.fullmatch(entry['id']):
        raise CatalogueError('invalid addon id')
    filename = entry['package_file']
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith('.tar'):
        raise CatalogueError('package_file must be a local .tar basename')
    package = package_root / filename
    if package.is_symlink():
        raise CatalogueError('package symlink not permitted')
    info = inspect_tar(package)
    assignments = re.findall(r'^[ \t]*name[ \t]*=', info, re.IGNORECASE | re.MULTILINE)
    quoted_id = re.escape(entry['id'])
    identity = re.compile(r'^[ \t]*name[ \t]*=[ \t]*(?:"' + quoted_id + r'"|\'' + quoted_id + r'\'|' + quoted_id + r')[ \t]*\r?$', re.IGNORECASE | re.MULTILINE)
    if len(assignments) != 1 or not identity.search(info):
        raise CatalogueError('addon.inf identity mismatch')
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    result = {k:v for k,v in entry.items() if k != 'package_file'}
    result['sha256'] = digest
    return result

def validate_freshness(issued_at, expires_at, now):
    if (type(issued_at) is not int or type(expires_at) is not int
            or issued_at < 1 or issued_at > now + 300
            or expires_at <= now or expires_at <= issued_at
            or expires_at - issued_at > 30 * 24 * 60 * 60):
        raise CatalogueError('catalogue outside validity window')


def validate_catalogue(catalogue, source_id, now=None):
    """Validate the published shape and the offline CMS freshness and size limits."""
    schema = json.loads(CATALOGUE_SCHEMA.read_text(encoding='utf-8'))
    errors = Draft202012Validator(schema).iter_errors(catalogue)
    error = next(errors, None)
    if error:
        location = '.'.join(str(part) for part in error.absolute_path) or 'catalogue'
        raise CatalogueError(f'invalid catalogue schema at {location}: {error.message}')
    if type(catalogue['schema_version']) is not int or catalogue['source_id'] != source_id:
        raise CatalogueError('invalid catalogue version or source identity')
    validate_freshness(catalogue['issued_at'], catalogue['expires_at'], int(time.time()) if now is None else now)
    addons = catalogue['addons']
    if len(addons) > MAX_ADDONS:
        raise CatalogueError('too many addons')
    seen = set()
    for addon in addons:
        addon_id = addon['id']
        if not ID.fullmatch(addon_id) or addon_id in seen:
            raise CatalogueError('invalid or duplicate addon ID')
        seen.add(addon_id)
        if any(len(addon[field].encode('utf-8')) > 512 for field in ('name', 'version', 'license')):
            raise CatalogueError('addon metadata exceeds size limit')
        if type(addon['cms_compatibility']['major']) is not int:
            raise CatalogueError('invalid CMS compatibility major version')
        url = addon['download_url']
        try:
            parsed = urlsplit(url)
            valid = (url.isascii() and len(url) <= 2048 and parsed.scheme == 'https'
                     and parsed.hostname and parsed.username is None and parsed.password is None
                     and parsed.port != 0 and not any(ord(char) <= 32 or ord(char) == 127 for char in url)
                     and '\\' not in url and '#' not in url)
        except ValueError:
            valid = False
        if not valid:
            raise CatalogueError(f'invalid download URL for {addon_id}')
    return catalogue


def encode_catalogue(catalogue):
    payload = (json.dumps(catalogue, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if len(payload) > MAX_CATALOGUE_BYTES:
        raise CatalogueError('catalogue exceeds size limit')
    return payload


def build(input_path, package_root, *, now=None):
    data = json.loads(input_path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1
            or not isinstance(data.get('source_id'), str) or not data['source_id']
            or not isinstance(data.get('addons'), list)):
        raise CatalogueError('invalid catalogue header')
    now = int(time.time()) if now is None else now
    validate_freshness(data.get('issued_at'), data.get('expires_at'), now)
    if len(data['addons']) > MAX_ADDONS:
        raise CatalogueError('too many addons')
    addons = [validate_entry(entry, package_root) for entry in data['addons']]
    catalogue = {
        'schema_version': 1,
        'source_id': data['source_id'],
        'issued_at': data['issued_at'],
        'expires_at': data['expires_at'],
        'addons': sorted(addons, key=lambda addon: addon['id']),
    }
    return validate_catalogue(catalogue, data['source_id'], now)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--package-root',type=Path,required=True)
    args=parser.parse_args()
    try:
        payload = encode_catalogue(build(args.input, args.package_root))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')
    print('Wrote unsigned catalogue:', args.output)

if __name__=='__main__':
    main()
