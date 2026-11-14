"""Resolver validation using substituted DNS records; no DNS server is contacted."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PHP = shutil.which('php')
SOURCE = Path(__file__).resolve().parents[2] / 'cms' / 'sources_custom' / 'extended_http_transport.php'


@unittest.skipUnless(PHP, 'PHP CLI is required')
class TransportDnsTests(unittest.TestCase):
    def test_dns_answer_validation(self):
        needle = '$records = dns_get_record($host, DNS_A | DNS_AAAA);'
        original = SOURCE.read_text()
        self.assertEqual(original.count(needle), 1)
        cases = [
            ("array(array('ip'=>'8.8.8.8'), array('ip'=>'127.0.0.1'))", 'REJECT'),
            ("array(array('ipv6'=>'::ffff:127.0.0.1'))", 'REJECT'),
            ("array(array('type'=>'CNAME'))", 'REJECT'),
            ("array(array('ip'=>'8.8.8.8'))", 'ACCEPT'),
        ]
        code = ('require $argv[1]; try { extended_transport_resolve_public("example.org"); '
                'echo "ACCEPT"; } catch (Throwable $e) { echo "REJECT"; }')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'transport.php'
            for records, expected in cases:
                with self.subTest(records=records):
                    path.write_text(original.replace(needle, '$records = ' + records + ';'))
                    result = subprocess.run([PHP, '-r', code, str(path)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
