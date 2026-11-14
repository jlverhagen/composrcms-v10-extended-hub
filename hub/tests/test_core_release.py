import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

PUBLISHER = Path(__file__).resolve().parents[1] / 'publisher'
sys.path.insert(0, str(PUBLISHER))
from build_release_manifest import build_manifest
from build_release_package import build_package

VERSION = '10.0.52-ext.1-alpha.1'
UPSTREAM_COMMIT = '0123456789abcdef0123456789abcdef01234567'
DOWNLOAD_URL = f'https://example.test/releases/composr-v10-extended-{VERSION}.tar.gz'


class CoreReleaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'empty').mkdir()
        (self.source / 'index.html').touch()
        (self.source / '.htaccess').write_bytes(b'fixture\n')
        (self.source / 'run.sh').write_bytes(b'#!/bin/sh\n')
        (self.source / 'run.sh').chmod(0o750)

    def test_reproducible_package_inventory_and_checksums(self):
        first = build_package(self.source, self.root / 'first', VERSION)
        for path in self.source.iterdir():
            os.utime(path, (1_000_000, 1_000_000))
        (self.source / 'run.sh').chmod(0o700)
        (self.source / '.htaccess').chmod(0o600)
        second = build_package(self.source, self.root / 'second', VERSION)
        self.assertEqual(first.read_bytes(), second.read_bytes())

        inventory = json.loads((first.parent / 'inventory.json').read_text())
        self.assertEqual(inventory['archive']['bytes'], first.stat().st_size)
        with tarfile.open(first, 'r:gz') as archive:
            root = first.name.removesuffix('.tar.gz')
            self.assertTrue(archive.getmember(root + '/empty').isdir())
            self.assertEqual({entry['path'] for entry in inventory['files']},
                             {member.name for member in archive if member.isfile()})
            for member in archive:
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
            for entry in inventory['files']:
                member = archive.getmember(entry['path'])
                self.assertEqual(entry['bytes'], member.size)
                self.assertEqual(entry['mode'], '0755' if member.name.endswith('/run.sh') else '0644')
                self.assertEqual(entry['mode'], format(member.mode, '04o'))
                self.assertEqual(entry['sha256'], hashlib.sha256(archive.extractfile(member).read()).hexdigest())
        sums = {}
        for line in (first.parent / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ', 1)
            sums[name] = digest
            self.assertEqual(digest, hashlib.sha256((first.parent / name).read_bytes()).hexdigest())
        self.assertEqual(sums, {first.name: inventory['archive']['sha256'],
                               'inventory.json': sums['inventory.json']})
        for name in ('inventory.json', 'SHA256SUMS'):
            self.assertEqual((first.parent / name).read_bytes(), (second.parent / name).read_bytes())

    def test_failed_package_leaves_no_destination(self):
        (self.source / 'link').symlink_to(self.source / 'run.sh')
        destination = self.root / 'package'
        with self.assertRaisesRegex(ValueError, 'non-regular'):
            build_package(self.source, destination, VERSION)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob('.release-*')))

    def test_manifest_rejects_invalid_release_inputs(self):
        archive = build_package(self.source, self.root / 'package', VERSION)
        defaults = dict(archive=archive, version=VERSION, upstream_base='10.0.52',
                        upstream_commit=UPSTREAM_COMMIT, download_url=DOWNLOAD_URL)
        for changes in (
            {'upstream_base': '10.0.51'},
            {'upstream_commit': 'main'},
            {'version': '10.0.52'},
            {'download_url': 'http://example.test/archive.tar.gz'},
            {'download_url': 'https://user@example.test/archive.tar.gz'},
            {'download_url': 'https://example.test/'},
            {'download_url': 'https:///archive.tar.gz'},
            {'download_url': DOWNLOAD_URL + '?token=x'},
            {'archive': self.root / 'missing.tar.gz'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_manifest(**(defaults | changes))

    def test_cli_package_manifest_and_detached_core_signature(self):
        def run(script, *args, check=True):
            return subprocess.run([sys.executable, str(PUBLISHER / script), *map(str, args)],
                                  capture_output=True, text=True, check=check)

        destination = self.root / 'package'
        package_args = ('--source-dir', self.source, '--output-dir', destination, '--version', VERSION)
        archive = Path(run('build_release_package.py', *package_args).stdout.strip())
        self.assertTrue(archive.is_file())
        self.assertNotEqual(run('build_release_package.py', *package_args, check=False).returncode, 0)

        manifest = self.root / 'releases.json'
        manifest_args = ('--archive', archive, '--version', VERSION, '--upstream-base', '10.0.52',
                         '--upstream-commit', UPSTREAM_COMMIT, '--download-url', DOWNLOAD_URL,
                         '--output', manifest)
        run('build_release_manifest.py', *manifest_args)
        self.assertNotEqual(run('build_release_manifest.py', *manifest_args, check=False).returncode, 0)
        raw = manifest.read_bytes()
        self.assertEqual(json.loads(raw), {
            'schema_version': 1,
            'distribution_id': 'composrcms-v10-extended',
            'releases': [{
                'version': VERSION,
                'upstream_base': '10.0.52',
                'upstream_commit': UPSTREAM_COMMIT,
                'download_url': DOWNLOAD_URL,
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            }],
        })

        core_key = Ed25519PrivateKey.generate()
        catalogue_key = Ed25519PrivateKey.generate()
        seed = self.root / 'core.seed'
        seed.touch(mode=0o600)
        seed.write_bytes(core_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
        envelope = self.root / 'releases.sig.json'
        run('sign_manifest.py', '--manifest', manifest, '--private-key', seed,
            '--key-id', 'fixture-core-release', '--signature-output', envelope)
        signed = json.loads(envelope.read_text())
        self.assertEqual(signed['key_id'], 'fixture-core-release')
        signature = base64.b64decode(signed['signature'], validate=True)
        core_key.public_key().verify(signature, raw)
        with self.assertRaises(InvalidSignature):
            core_key.public_key().verify(signature, raw + b' ')
        with self.assertRaises(InvalidSignature):
            catalogue_key.public_key().verify(signature, raw)
