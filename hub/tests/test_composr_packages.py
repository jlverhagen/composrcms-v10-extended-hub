"""Build real installer formats from a small source fixture and reject corruption."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'publisher'))
from build_composr_installers import build
from catalogue_enforcement import GUARDED_FILES
from verify_composr_packages import verify

VERSION = '2026.11.1-alpha.1'
PHP = shutil.which('php')


@unittest.skipUnless(PHP, 'PHP CLI required')
class ComposrPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        files = {name: b'<?php\n' for name in GUARDED_FILES}
        files.update({
            'sources/hooks/systems/addon_registry/core.php':
                b'<?php class Fixture { public function get_file_list()\n    {\n        return array(\n); }}',
            'sources_custom/extended_version.php':
                b"<?php function extended_distribution_version() { return 'dev'; }",
            'themes/default/templates_custom/EXTENDED_ADDON_INSTALL_CANCEL.tpl': b'fixture',
            'sources_custom/hooks/systems/page_groupings/extended_addons.php': b'<?php',
            'data/images/advertise_here.png': b'fixture image',
            'sources/version.php': b'<?php /* 1234567890 */',
        })
        for name, data in files.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for name in ('install.php', 'install.sql', '_config.php.template', 'data_custom/builds/readme.txt'):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fixture')
        (source / 'data/files.bin').write_bytes(subprocess.check_output([PHP, '-r',
            'echo serialize(array_fill_keys(json_decode(stream_get_contents(STDIN),true), []));'],
            input=json.dumps(list(files)).encode()))
        self.output = self.root / 'package'
        build(source, self.output, VERSION)

    def rehash(self):
        (self.output / 'SHA256SUMS').write_text(''.join(
            f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
            for path in sorted(self.output.iterdir()) if path.name != 'SHA256SUMS'))

    def test_real_formats_and_quick_index_pass(self):
        result = verify(self.output, VERSION, PHP)
        self.assertEqual(result['guarded_files'], len(GUARDED_FILES))
        self.assertEqual(result['core_payload_files'], result['integrity_entries'] + 1)

    def test_changed_archive_fails_digest(self):
        path = self.output / f'composr_upgrader-{VERSION}.cms'
        path.write_bytes(path.read_bytes() + b'corruption')
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            verify(self.output, VERSION, PHP)

    def test_rehashed_manual_payload_change_still_fails(self):
        path = self.output / f'composr_manualextraction_installer-{VERSION}.zip'
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files['sources/version.php'] += b'changed'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        self.rehash()
        with self.assertRaisesRegex(ValueError, 'Manual installer payload mismatch'):
            verify(self.output, VERSION, PHP)

    def test_rehashed_excluded_member_still_fails(self):
        path = self.output / f'composr_upgrader-{VERSION}.cms'
        with tarfile.open(path, 'a') as archive:
            member = tarfile.TarInfo('tracker/index.php')
            member.size = 1
            archive.addfile(member, io.BytesIO(b'x'))
        self.rehash()
        with self.assertRaisesRegex(ValueError, 'Excluded release member'):
            verify(self.output, VERSION, PHP)


if __name__ == '__main__':
    unittest.main()
