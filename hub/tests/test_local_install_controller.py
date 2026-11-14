import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

PHP = shutil.which('php')
CMS = Path(__file__).resolve().parents[2] / 'cms'
HARNESS = Path(__file__).with_name('check-local-install-controller.php')


@unittest.skipUnless(PHP, 'PHP CLI required')
class LocalInstallControllerTests(unittest.TestCase):
    def test_confirmation_dispatch_and_write_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'fixture.tar'
            with tarfile.open(archive, 'w', format=tarfile.USTAR_FORMAT) as tar:
                for name, content in [('addon.inf', b'name="fixture"\n'), ('assets/readme.txt', b'fixture\n')]:
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    tar.addfile(member, io.BytesIO(content))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            result = subprocess.run(
                [PHP, str(HARNESS), str(CMS), str(root), str(archive), digest],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(result.stdout.strip(), 'Controller checks passed')
