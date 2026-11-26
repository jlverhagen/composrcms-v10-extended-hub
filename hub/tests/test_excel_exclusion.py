"""Exercise the Extended core package exclusion without running an installer."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'publisher'))
from verify_composr_packages import validate_names
import build_composr_installers
import build_release_package
from check_release_staging import check_staging


class SpreadsheetExclusionTests(unittest.TestCase):
    def test_spreadsheet_payload_is_rejected(self):
        for name in (
            'sources_custom/hooks/systems/addon_registry/excel_support.php',
            'sources_custom/files2.php',
            'sources_custom/files_spout.php',
            'sources_custom/spout',
            'sources_custom/spout/src/Spout/Reader/XLSX.php',
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Excluded release member'):
                validate_names([name])

    def test_unrelated_core_files_are_accepted(self):
        validate_names(['sources/files2.php', 'sources_custom/other_addon.php'])

    def test_installer_builder_rejects_excluded_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            (source / 'sources_custom').mkdir(parents=True)
            output = Path(directory) / 'output'
            with mock.patch.object(build_composr_installers, 'inventory', return_value=['sources_custom/spout/src/Spout/Reader/XLSX.php']):
                with self.assertRaisesRegex(ValueError, 'Excluded spreadsheet addon payload'):
                    build_composr_installers.build(source, output, '2026.11.1-alpha.1')
            self.assertFalse(output.exists())

    def test_source_archive_rejects_excluded_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            blocked = source / 'sources_custom/spout/src/Spout/Reader/XLSX.php'
            blocked.parent.mkdir(parents=True)
            blocked.write_text('<?php')
            findings = check_staging(source)
            self.assertTrue(any('excluded spreadsheet addon payload' in e['findings'] for e in findings))
            with self.assertRaisesRegex(ValueError, 'excluded spreadsheet addon payload'):
                build_release_package.build_package(source, Path(directory) / 'output', '2026.11.1-alpha.1')
            self.assertFalse((Path(directory) / 'output').exists())


if __name__ == '__main__':
    unittest.main()
