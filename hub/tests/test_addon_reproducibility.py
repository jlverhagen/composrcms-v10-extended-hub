"""Check reproducibility using the real addon exporter and a reviewed CMS tree."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

PHP = os.environ.get('PHP_BINARY') or shutil.which('php')
ROOT = Path(__file__).resolve().parents[2]
CMS = Path(os.environ.get('COMPOSR_TEST_CMS', str(ROOT / 'cms')))
BUILDER = ROOT / 'hub/publisher/build_addon_tars.php'


@unittest.skipUnless(PHP and (CMS / 'sources_custom/hooks/systems/addon_registry/less.php').is_file(),
                     'PHP and reviewed CMS tree required')
class AddonReproducibilityTests(unittest.TestCase):
    def test_less_package_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp) / 'first', Path(temp) / 'second'
            first.mkdir()
            second.mkdir()
            for output in (first, second):
                result = subprocess.run([PHP, str(BUILDER), str(CMS), str(output), 'less'],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            a, b = first / 'less-10.x.tar', second / 'less-10.x.tar'
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with tarfile.open(a) as archive:
                self.assertEqual(archive.getmember('addon.inf').mtime, 0)
                payload = archive.extractfile('sources_custom/ILess/Node.php').read()
                self.assertEqual(payload, (CMS / 'sources_custom/ILess/Node.php').read_bytes())


if __name__ == '__main__':
    unittest.main()
