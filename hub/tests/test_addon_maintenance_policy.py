"""Exercise publication selection with inert source adapters, not TAR generation."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PHP = os.environ.get('PHP_BINARY') or shutil.which('php')
BUILDER = Path(__file__).resolve().parents[1] / 'publisher/build_addon_tars.php'
EXCLUDED = 'composr_homesite_support_credits'
EXCLUDED_SPREADSHEET = 'excel_support'
EXCLUDED_NESTED_CSV = 'nested_cpf_csv_lists'


@unittest.skipUnless(PHP, 'PHP CLI required')
class AddonMaintenancePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.output = self.root / 'output'
        self.output.mkdir()
        sources = self.source / 'sources'
        sources.mkdir(parents=True)
        registry = self.source / 'sources_custom/hooks/systems/addon_registry'
        registry.mkdir(parents=True)
        for name in ('global3', 'zones', 'version', 'tar', 'addons'):
            (sources / (name + '.php')).write_text('<?php\n')
        (sources / 'version2.php').write_text('<?php function get_version_branch($v) { return "10.x"; }')
        (sources / 'addons2.php').write_text('''<?php
file_put_contents(get_custom_file_base().'/source-loaded', 'yes');
function read_addon_info($id, ...$args) {
    if ($id !== 'fixture') throw new RuntimeException('Excluded registry reached');
    return array('files'=>array('payload.txt'), 'version'=>10.0, 'name'=>'fixture',
      'incompatibilities'=>array(), 'dependencies'=>array(), 'author'=>'fixture',
      'organisation'=>'fixture', 'category'=>'fixture', 'copyright_attribution'=>array(),
      'licence'=>'fixture', 'description'=>'fixture');
}
function create_addon($filename, $files, $name, $incompat, $deps, $author, $org,
  $version, $category, $copyright, $licence, $description, $stage, $unused, $source, $metadata_mtime) {
    if ($metadata_mtime !== 0) throw new RuntimeException('Metadata timestamp was not fixed');
    file_put_contents(get_custom_file_base().'/'.$stage.'/'.$filename, 'fixture');
}
''')
        for name in ('fixture', EXCLUDED, EXCLUDED_SPREADSHEET, EXCLUDED_NESTED_CSV):
            (registry / (name + '.php')).write_text('<?php\n')
        (self.source / 'payload.txt').write_text('fixture')

    def run_builder(self, *ids):
        return subprocess.run([PHP, '-d', 'error_reporting=-1', str(BUILDER),
            str(self.source), str(self.output), *ids], capture_output=True, text=True, timeout=20)

    def test_explicit_excluded_request_stops_before_source_execution(self):
        for addon in (EXCLUDED, EXCLUDED_SPREADSHEET, EXCLUDED_NESTED_CSV):
            with self.subTest(addon=addon):
                result = self.run_builder(addon)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('excluded by Extended maintenance policy', result.stderr)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_mixed_request_is_rejected_without_partial_build(self):
        for addon in (EXCLUDED, EXCLUDED_SPREADSHEET, EXCLUDED_NESTED_CSV):
            with self.subTest(addon=addon):
                result = self.run_builder('fixture', addon)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_automatic_selection_skips_excluded_registry(self):
        result = self.run_builder()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout.strip(), 'fixture-10.x.tar')
        self.assertEqual((self.output / 'fixture-10.x.tar').read_text(), 'fixture')
        self.assertFalse(any(EXCLUDED in p.name for p in self.output.iterdir()))
        self.assertFalse(any(EXCLUDED_SPREADSHEET in p.name for p in self.output.iterdir()))
        self.assertFalse(any(EXCLUDED_NESTED_CSV in p.name for p in self.output.iterdir()))

    def test_explicit_maintained_addon_still_builds(self):
        result = self.run_builder('fixture')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertTrue((self.output / 'fixture-10.x.tar').is_file())

    def test_old_core_without_metadata_timestamp_is_rejected(self):
        path = self.source / 'sources/addons2.php'
        content = path.read_text().replace(', $source, $metadata_mtime)', ', $source)')
        path.write_text(content)
        result = self.run_builder('fixture')
        self.assertEqual(result.returncode, 2)
        self.assertIn('lacks generated metadata timestamp support', result.stderr)
        self.assertFalse((self.output / 'fixture-10.x.tar').exists())


if __name__ == '__main__':
    unittest.main()

