import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

PUBLISHER = Path(__file__).resolve().parents[1] / 'publisher'
sys.path.insert(0, str(PUBLISHER))
from build_release_manifest import build_manifest
from build_release_package import build_package
from sign_manifest import sign
from verify_release import verify_release

VERSION = '10.0.52-ext.1'
KEY_ID = 'core-release'


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'index.html').write_text('fixture')
        (self.source / '.htaccess').touch()
        (self.source / 'empty').mkdir()

    def run_cli(self, command, *args):
        return subprocess.run([sys.executable, str(PUBLISHER / command), *map(str, args)],
                              capture_output=True, text=True)

    def package(self):
        archive = build_package(self.source, self.root / 'package', VERSION)
        manifest = archive.parent / 'releases.json'
        envelope = archive.parent / 'releases.sig.json'
        public_key = self.root / 'public.txt'
        metadata = build_manifest(archive, VERSION, '10.0.52', '1' * 40,
                                  'https://example.test/' + archive.name)
        raw = json.dumps(metadata).encode()
        seed = Ed25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        signature, pin = sign(raw, seed, KEY_ID)
        manifest.write_bytes(raw)
        envelope.write_text(json.dumps(signature))
        public_key.write_text(pin + '\n')
        return dict(manifest=manifest, signature=envelope, public_key=public_key, key_id=KEY_ID,
                    version=VERSION, archive=archive, inventory=archive.parent / 'inventory.json')

    def test_staging_report_matches_packaged_file_inventory(self):
        result = self.run_cli('check_release_staging.py', '--source-dir', self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = json.loads(result.stdout)
        self.assertEqual({row['path'] for row in entries}, {'.', '.htaccess', 'empty', 'index.html'})
        package = self.package()
        files = json.loads(package['inventory'].read_text())['files']
        inventory = {row['path'].partition('/')[2]: (row['bytes'], row['mode']) for row in files}
        report = {row['path']: (row['bytes'], row['mode']) for row in entries if row['type'] == 'file'}
        self.assertEqual(report, inventory)

    def test_staging_flags_paths_and_reports_no_file_contents(self):
        (self.source / '.git').mkdir()
        (self.source / '.git' / 'config').touch()
        for name in ('.env', '.env.local', '.env.example', '_config.php', 'core.seed'):
            (self.source / name).write_text('fixture content')
        (self.source / 'opaque.txt').write_text('-----BEGIN PRIVATE KEY-----\nfixture-key-content\n')
        (self.source / 'link').symlink_to(self.root)
        result = self.run_cli('check_release_staging.py', '--source-dir', self.source)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('fixture-key-content', result.stdout)
        entries = {row['path']: row['findings'] for row in json.loads(result.stdout)}
        self.assertEqual({name for name, findings in entries.items() if findings},
                         {'.git', '.git/config', '.env', '.env.local', '_config.php',
                          'core.seed', 'opaque.txt', 'link'})
        self.assertFalse(any(name.startswith('link/') for name in entries))
        self.assertEqual(self.run_cli('check_release_staging.py', '--source-dir',
                                      self.root / 'missing').returncode, 2)

    def test_verification_cli_accepts_signed_release(self):
        package = self.package()
        args = [value for key, setting in package.items()
                for value in ('--' + key.replace('_', '-'), setting)]
        result = self.run_cli('verify_release.py', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            'archive_sha256': hashlib.sha256(package['archive'].read_bytes()).hexdigest(),
            'verified_files': 2,
            'version': VERSION,
        })

    def test_verifier_rejects_wrong_key_version_and_archive(self):
        package = self.package()
        with self.assertRaisesRegex(ValueError, 'key ID'):
            verify_release(**(package | {'key_id': 'other'}))
        with self.assertRaisesRegex(ValueError, 'requested release version'):
            verify_release(**(package | {'version': '10.0.52-ext.2'}))
        other_pin = self.root / 'other.txt'
        other_pin.write_text(sign(b'fixture', bytes(range(32)), KEY_ID)[1])
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            verify_release(**(package | {'public_key': other_pin}))
        archive = package['archive']
        archive.write_bytes(archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'archive SHA-256'):
            verify_release(**package)

    def test_verifier_rejects_changed_manifest_and_inventory(self):
        package = self.package()
        raw = package['manifest'].read_bytes()
        package['manifest'].write_bytes(raw + b' ')
        with self.assertRaisesRegex(ValueError, 'signature verification failed'):
            verify_release(**package)
        package['manifest'].write_bytes(raw)

        path = package['inventory']
        original = path.read_bytes()
        for field, value, message in (
            ('sha256', '0' * 64, 'digest'),
            ('mode', '0755', 'metadata'),
            ('bytes', 42, 'metadata'),
        ):
            with self.subTest(field=field):
                inventory = json.loads(original)
                inventory['files'][0][field] = value
                path.write_text(json.dumps(inventory))
                with self.assertRaisesRegex(ValueError, message):
                    verify_release(**package)
        inventory = json.loads(original)
        inventory['files'].pop()
        path.write_text(json.dumps(inventory))
        with self.assertRaisesRegex(ValueError, 'metadata'):
            verify_release(**package)
        inventory = json.loads(original)
        inventory['files'].append(inventory['files'][0] | {'path': 'absent.txt'})
        path.write_text(json.dumps(inventory))
        with self.assertRaisesRegex(ValueError, 'missing from archive'):
            verify_release(**package)
