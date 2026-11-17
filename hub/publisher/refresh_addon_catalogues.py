#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

APPROVE = r'''
require "sources_custom/extended_manifest_verify.php";
require "sources_custom/extended_catalogue_snapshot.php";
require "sources_custom/extended_catalogue_high_water.php";
[$state, $root, $id, $browserConfig] = array_slice($argv, 1);
$config = json_decode(file_get_contents($browserConfig), true, 64, JSON_THROW_ON_ERROR);
foreach ($config["sources"] as $source) {
    if ($source["id"] !== $id || !$source["enabled"]) continue;
    $keys = $source["trusted_keys"];
    $ids = $source["allowed_key_ids"];
    $record = "$state/catalogue-high-water.json";
    $snapshot = extended_stage_signed_catalogue_snapshot(
        "$root/catalogue.json", "$root/catalogue.sig.json", $keys, $ids, $id, $state
    );
    $group = filegroup($record);
    foreach (["manifest_path", "signature_path"] as $which) {
        if (!chgrp($snapshot[$which], $group) || !chmod($snapshot[$which], 0640)) exit(4);
    }
    $directory = dirname($snapshot["manifest_path"]);
    if (!chgrp($directory, $group) || !chmod($directory, 0750)) exit(5);
    if (!is_executable("/usr/sbin/restorecon")) exit(6);
    exec("/usr/sbin/restorecon -R " . escapeshellarg($directory), $unused, $status);
    if ($status !== 0) exit(6);
    extended_approve_catalogue_high_water(
        $record, $id, file_get_contents($snapshot["manifest_path"]),
        file_get_contents($snapshot["signature_path"]), $keys, $ids
    );
    exec("/usr/sbin/restorecon " . escapeshellarg($record), $unused, $status);
    exit($status);
}
exit(3);
'''

def get_url(url, cap):
    return subprocess.check_output([
        'curl', '-fsSL', '--proto', '=https', '--proto-redir', '=https',
        '--max-redirs', '1', '--max-time', '60', '--max-filesize', str(cap), url,
    ])

def renew_source(source_id, source, settings, enabled, approved, stage, force):
    state = Path(settings['state'])
    site = Path(settings['site'])
    entry = approved[source_id]
    identity = entry['sha256']
    previous = state / f'{source_id}-{identity}' / 'catalogue.json'
    if not previous.exists():
        previous = Path(enabled[source_id]['manifest_path'])
    previous_bytes = previous.read_bytes()
    if hashlib.sha256(previous_bytes).hexdigest() != identity:
        raise ValueError('approved digest mismatch')
    current = json.loads(previous_bytes)
    if not force and current['expires_at'] - time.time() > settings['renew_within_days'] * 86400:
        print(f'{source_id}: current catalogue within validity window', flush=True)
        return

    renewed = stage / source_id
    tool = Path(__file__).with_name('renew_addon_catalogue.py')
    subprocess.run([
        sys.executable, str(tool), '--previous', str(previous),
        '--approved-sha256', identity, '--package-root', source['packages'],
        '--private-key', source['private_key'], '--key-id', source['key_id'],
        '--days', str(settings['validity_days']), '--output', str(renewed),
    ], check=True)
    manifest = renewed / 'catalogue.json'
    signature = renewed / 'catalogue.sig.json'
    asset_bases = source.get('asset_bases', [source['asset_base']])
    if not isinstance(asset_bases, list) or not asset_bases or any(
        not isinstance(base, str) or not base.startswith('https://') for base in asset_bases
    ):
        raise ValueError('invalid addon asset bases')
    for addon in current['addons']:
        url = addon['download_url']
        filename = Path(urlsplit(url).path).name
        if url not in {f"{base.rstrip('/')}/{filename}" for base in asset_bases} or not filename.endswith('.tar'):
            raise ValueError('unexpected addon asset URL')
        if hashlib.sha256(get_url(url, 52428800)).hexdigest() != addon['sha256']:
            raise ValueError(f"remote TAR checksum mismatch for {addon['id']}")

    folder = source_id + '-' + hashlib.sha256(manifest.read_bytes()).hexdigest()
    published = Path(settings['publish_directory']) / folder
    exposed = stage / (source_id + '-public')
    exposed.mkdir(mode=0o755)
    for file in (manifest, signature):
        target = exposed / file.name
        shutil.copyfile(file, target)
        target.chmod(0o644)
    exposed.chmod(0o755)
    if not published.exists():
        os.rename(exposed, published)
    subprocess.run(['/usr/sbin/restorecon', '-R', str(published)], check=True)
    for file, cap in ((manifest, 2097152), (signature, 4096)):
        url = f"{settings['publish_base'].rstrip('/')}/{folder}/{file.name}"
        if get_url(url, cap) != file.read_bytes():
            raise ValueError('published catalogue bytes differ')
    subprocess.run([
        settings['php'], '-r', APPROVE, str(state), str(renewed), source_id,
        settings['browser_config'],
    ], cwd=site, check=True)
    print(f'{source_id}: renewed and approved ({folder})', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Renew configured Composr addon catalogues.')
    parser.add_argument('config', type=Path)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    config = args.config
    mode = config.stat()
    if config.is_symlink() or not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid() or mode.st_mode & 0o022:
        parser.error('configuration must be a regular operator-owned file without group or other write access')
    settings = json.loads(config.read_text())
    if not 0 <= settings['renew_within_days'] < settings['validity_days'] <= 30:
        parser.error('invalid renewal window')
    approved = json.loads((Path(settings['state']) / 'catalogue-high-water.json').read_text())['sources']
    browser = json.loads(Path(settings['browser_config']).read_text())
    enabled = {source['id']: source for source in browser['sources'] if source['enabled']}
    failed = []
    with tempfile.TemporaryDirectory(prefix='.catalogue-renewal-', dir=settings['staging_parent']) as tmp:
        stage = Path(tmp)
        for source_id, source in settings['sources'].items():
            try:
                if not all(c.isascii() and (c.isalnum() or c in '_-') for c in source_id) or not source_id:
                    raise ValueError('invalid source ID')
                renew_source(source_id, source, settings, enabled, approved, stage, args.force)
            except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
                print(f'{source_id}: {error}', file=sys.stderr, flush=True)
                failed.append(source_id)
    if failed:
        raise SystemExit('Catalogue renewal failed for: ' + ', '.join(failed))


if __name__ == '__main__':
    main()
