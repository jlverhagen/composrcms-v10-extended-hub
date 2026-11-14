import os, shutil, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'cms/sources_custom'
class HardeningTests(unittest.TestCase):
    def run_php(self, code, *args):
        if not shutil.which('php'): self.skipTest('PHP unavailable')
        with tempfile.TemporaryDirectory() as d:
            script=Path(d)/'check.php';script.write_text('<?php\n'+code)
            return subprocess.run(['php',str(script),*map(str,args)],capture_output=True,text=True)
    def test_url_policy(self):
        code='''require $argv[1]; foreach (array_slice($argv,2) as $url) {try {extended_transport_validate_url($url);echo "OK\\n";} catch (Throwable $e) {echo "NO\\n";}}'''
        urls=['https://example.org/addons.json','https://user:pass@example.org/a','https://example.org:8443/a','https://127.0.0.1/a','https://2130706433/a','https://example.org/a#frag','https://example.org/a']
        p=self.run_php(code,SRC/'extended_http_transport.php',*urls)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.splitlines(),['OK','NO','NO','NO','NO','NO','OK'])
    def test_symlink_and_hardlink_state_files(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'state';state.mkdir(mode=0o700)
            target=Path(d)/'target';target.write_text('sensitive')
            link=state/'registry-state.json';link.symlink_to(target)
            code='''require $argv[1]; try {extended_registry_check_existing_file($argv[2]);echo "OK";} catch (Throwable $e) {echo "NO";}'''
            p=self.run_php(code,SRC/'extended_registry_trust.php',link)
            self.assertEqual(p.stdout,'NO',p.stderr)
            link.unlink();os.link(target,link)
            p=self.run_php(code,SRC/'extended_registry_trust.php',link)
            self.assertEqual(p.stdout,'NO',p.stderr)
    def test_world_writable_state_dir(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'state';state.mkdir();state.chmod(0o777)
            code='''require $argv[1];try {extended_registry_check_directory($argv[2]);echo "OK";}catch(Throwable $e){echo "NO";}'''
            p=self.run_php(code,SRC/'extended_registry_trust.php',state)
            self.assertEqual(p.stdout,'NO',p.stderr)
if __name__=='__main__': unittest.main()
