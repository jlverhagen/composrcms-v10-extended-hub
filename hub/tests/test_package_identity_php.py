import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


PHP = shutil.which('php')
SOURCE = Path(__file__).resolve().parents[2] / 'cms' / 'sources_custom' / 'extended_addon_download.php'


@unittest.skipUnless(PHP, 'PHP CLI is required')
class PackageIdentityTests(unittest.TestCase):
    def verify(self, metadata, extra_entries=(), mutate=None):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'addon.tar'
            contents = metadata.encode('utf-8')
            with tarfile.open(archive, 'w', format=tarfile.USTAR_FORMAT) as tar:
                info = tarfile.TarInfo('addon.inf')
                info.size = len(contents)
                tar.addfile(info, io.BytesIO(contents))
                for name, entry_type in extra_entries:
                    info = tarfile.TarInfo(name)
                    info.type = entry_type
                    tar.addfile(info, io.BytesIO(b'') if entry_type == tarfile.REGTYPE else None)
            if mutate is not None:
                archive.write_bytes(mutate(archive.read_bytes()))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            code = (
                f'require {json.dumps(str(SOURCE))}; '
                'try { '
                f'extended_verify_local_addon_package({json.dumps(str(archive))}, '
                f'{json.dumps(digest)}, "example");'
                '} catch (RuntimeException $error) { '
                'fwrite(STDERR, $error->getMessage() . PHP_EOL); exit(1); }'
            )
            return subprocess.run([PHP, '-r', code], capture_output=True, text=True)

    def test_hidden_data_after_end_marker_is_rejected(self):
        def append_data(data):
            return data + b'X' * 512
        result = self.verify('name="example"\n', mutate=append_data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('after TAR end marker', result.stderr)

    def test_missing_end_marker_is_rejected(self):
        # This metadata fits in one data block after its 512-byte header.
        result = self.verify('name="example"\n', mutate=lambda data: data[:1024])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing TAR end marker', result.stderr)

    def test_incomplete_end_marker_is_rejected(self):
        result = self.verify('name="example"\n', mutate=lambda data: data[:1536])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Incomplete TAR end marker', result.stderr)

    def test_matching_name_is_accepted(self):
        result = self.verify('name="example"\nversion="1.0"\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_duplicate_name_is_rejected(self):
        result = self.verify('name="example"\nname="different"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('identity mismatch', result.stderr)

    def test_mismatched_quotes_are_rejected(self):
        result = self.verify('name="example\'\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('identity mismatch', result.stderr)

    def test_repeated_path_separator_is_rejected(self):
        result = self.verify('name="example"\n', [('dir//file', tarfile.REGTYPE)])
        self.assertNotEqual(result.returncode, 0)

    def test_file_and_directory_collision_is_rejected(self):
        result = self.verify('name="example"\n', [
            ('dir/file', tarfile.REGTYPE), ('dir', tarfile.REGTYPE)
        ])
        self.assertNotEqual(result.returncode, 0)

    def test_normal_directory_and_file_are_accepted(self):
        result = self.verify('name="example"\n', [
            ('dir/', tarfile.DIRTYPE), ('dir/file', tarfile.REGTYPE)
        ])
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
