"""Fail-closed transport checks. No network access required."""
import json, subprocess, unittest
from pathlib import Path
CMS = Path(__file__).resolve().parents[2] / 'cms' / 'sources_custom'

def run(expression):
    code = 'require ' + json.dumps(str(CMS/'extended_http_transport.php')) + '; ' + expression
    return subprocess.run(['php', '-r', code], text=True, capture_output=True)

class TransportTests(unittest.TestCase):
    def test_reject_urls(self):
        for url in ['http://example.org/a', 'https://127.0.0.1/a', 'https://localhost/a',
                    'https://example.org:8443/a', 'https://u:p@example.org/a',
                    'https://example.org/a#fragment', 'https://example.org\n/a',
                    'https://foo.local/a', 'https://foo..example.org/a']:
            p=run('extended_transport_validate_url(' + json.dumps(url) + ');')
            self.assertNotEqual(p.returncode,0,url)
    def test_public_ip(self):
        for ip in ['127.0.0.1','10.0.0.1','192.168.1.1','169.254.169.254','::1','fc00::1','0.0.0.0',
                   '::ffff:127.0.0.1','::ffff:10.0.0.1','100.64.0.1','100.127.255.255',
                   '192.0.0.1','192.0.2.1','198.18.0.1','198.19.255.255','198.51.100.1',
                   '203.0.113.1','224.0.0.1','64:ff9b::7f00:1','64:ff9b:1::1',
                   '100::1','2002:7f00:1::1','2001:2::1','3fff::1']:
            p=run('echo extended_transport_is_public_ip(' + json.dumps(ip) + ') ? "yes" : "no";')
            self.assertEqual(p.stdout,'no',ip)
        for ip in ['8.8.8.8','1.1.1.1','100.63.255.255','100.128.0.1','198.20.0.1','2606:4700:4700::1111']:
            p=run('echo extended_transport_is_public_ip(' + json.dumps(ip) + ') ? "yes" : "no";')
            self.assertEqual(p.stdout,'yes',ip)
    def test_no_network_for_localhost(self):
        p=run('extended_transport_fetch("https://localhost/file", sys_get_temp_dir());')
        self.assertNotEqual(p.returncode,0)

if __name__ == '__main__': unittest.main()
