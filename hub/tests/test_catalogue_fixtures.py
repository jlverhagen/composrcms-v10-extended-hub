import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'hub/tests/fixtures/catalogues'
sys.path.insert(0, str(ROOT / 'hub/publisher'))
from build_catalogue import CatalogueError, build, encode_catalogue, validate_catalogue
from sign_manifest import sign

NOW = 1800000000
KEY_ID = 'fixture-catalogue'
SOURCE_ID = 'extended-hub'
CASES = (
    ('valid', 'valid', 'ACCEPT'),
    ('expired', 'expired', 'EXPIRED'),
    ('tampered', 'valid', 'SIGNATURE'),
)
PHP = shutil.which('php')


class CatalogueFixtureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.packages = Path(directory.name)
        self.package = self.packages / 'example.tar'
        with tarfile.open(self.package, 'w', format=tarfile.USTAR_FORMAT) as archive:
            content = b'name=example\n'
            member = tarfile.TarInfo('addon.inf')
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))

    def test_builder_matches_fixture_bytes_and_package_hash(self):
        catalogue = build(FIXTURES / 'source.json', self.packages, now=NOW)
        payload = encode_catalogue(catalogue)
        self.assertEqual(payload, (FIXTURES / 'valid.json').read_bytes())
        self.assertEqual(catalogue['addons'][0]['sha256'], hashlib.sha256(self.package.read_bytes()).hexdigest())
        envelope, public = sign(payload, bytes(range(32)), KEY_ID)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public)).verify(
            base64.b64decode(envelope['signature']), payload)

    def test_builder_rejects_invalid_catalogue_inputs(self):
        for field, value, message in (
            ('issued_at', None, 'validity window'),
            ('issued_at', True, 'validity window'),
            ('issued_at', NOW + 301, 'validity window'),
            ('expires_at', NOW, 'validity window'),
            ('expires_at', NOW + 31 * 86400, 'validity window'),
            ('name', 7, 'catalogue schema'),
            ('download_url', 'https://user@example.test/addon.tar', 'invalid download URL'),
            ('cms_compatibility', {'major': 11, 'minimum': '11.0'}, 'catalogue schema'),
            ('php_compatibility', {}, 'catalogue schema'),
            ('priority', 100, 'catalogue schema'),
        ):
            with self.subTest(field=field, value=value):
                data = json.loads((FIXTURES / 'source.json').read_bytes())
                container = data if field in ('issued_at', 'expires_at') else data['addons'][0]
                if value is None:
                    del container[field]
                else:
                    container[field] = value
                source = self.packages / 'invalid.json'
                source.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaisesRegex(CatalogueError, message):
                    build(source, self.packages, now=NOW)

    def test_fixed_signatures_and_validity_in_python(self):
        pin = base64.b64decode((FIXTURES / 'public-key.txt').read_bytes().strip(), validate=True)
        key = Ed25519PublicKey.from_public_bytes(pin)
        for manifest, signature, expected in CASES:
            with self.subTest(manifest=manifest):
                payload = (FIXTURES / f'{manifest}.json').read_bytes()
                envelope = json.loads((FIXTURES / f'{signature}.sig.json').read_bytes())
                self.assertEqual((envelope['algorithm'], envelope['key_id']), ('Ed25519', KEY_ID))
                signed = base64.b64decode(envelope['signature'], validate=True)
                if expected == 'SIGNATURE':
                    with self.assertRaises(InvalidSignature):
                        key.verify(signed, payload)
                else:
                    key.verify(signed, payload)
                    data = json.loads(payload)
                    if expected == 'EXPIRED':
                        with self.assertRaisesRegex(CatalogueError, 'validity window'):
                            validate_catalogue(data, SOURCE_ID, now=NOW)
                    else:
                        self.assertEqual(validate_catalogue(data, SOURCE_ID, now=NOW)['source_id'], SOURCE_ID)


@unittest.skipUnless(PHP, 'PHP CLI is required')
class CatalogueFixturePhpTests(unittest.TestCase):
    def test_fixed_signatures_and_validity_in_php(self):
        code = """
            require $argv[1];
            try {
                $pin = trim(file_get_contents($argv[4]));
                extended_verify_local_catalogue($argv[2], $argv[3], [$argv[5] => $pin],
                    [$argv[5]], $argv[6], (int)$argv[7]);
                echo 'ACCEPT';
            } catch (RuntimeException $error) {
                echo match ($error->getMessage()) {
                    'Catalogue outside validity window' => 'EXPIRED',
                    'Manifest signature verification failed' => 'SIGNATURE',
                    default => $error->getMessage(),
                };
            }
        """
        for manifest, signature, expected in CASES:
            with self.subTest(manifest=manifest):
                result = subprocess.run([
                    PHP, '-r', code, '--', str(ROOT / 'cms/sources_custom/extended_addon_catalogue.php'),
                    str(FIXTURES / f'{manifest}.json'), str(FIXTURES / f'{signature}.sig.json'),
                    str(FIXTURES / 'public-key.txt'), KEY_ID, SOURCE_ID, str(NOW),
                ], capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, expected, result.stderr)
