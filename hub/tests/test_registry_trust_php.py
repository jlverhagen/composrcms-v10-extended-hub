import base64, json, os, shutil, subprocess, tempfile, time, unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
ROOT=Path(__file__).resolve().parents[2]
PHP=ROOT/'cms/sources_custom/extended_registry_trust.php'
class RegistryTrustTests(unittest.TestCase):
    def test_signed_registry_replay_rollback_expiry_and_equivocation(self):
        if not shutil.which('php'): self.skipTest('php not available')
        key=Ed25519PrivateKey.generate()
        pub=base64.b64encode(key.public_key().public_bytes(encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)).decode()
        now=int(time.time())
        def signed(seq, expires=None, name='Hub'):
            m={'schema_version':1,'registry_id':'composrcms-v10-extended','sequence':seq,'issued_at':now-10,'expires_at':expires if expires is not None else now+3600,'sources':[{'id':'hub','name':name,'manifest_url':'https://example.org/catalogue.json','enabled':True,'signing_key_ids':['hub-key']}]}
            raw=json.dumps(m,separators=(',',':')).encode()
            sig={'algorithm':'Ed25519','key_id':'root','signature':base64.b64encode(key.sign(raw)).decode()}
            return raw.decode(),json.dumps(sig)
        with tempfile.TemporaryDirectory() as d:
            script='''<?php
require $argv[1];
try { extended_registry_accept(base64_decode($argv[2]), base64_decode($argv[3]), array('root'=>$argv[4]), array('root'), $argv[5], (int)$argv[6]); echo 'OK'; }
catch (Throwable $e) { echo 'REJECT'; }
'''
            test=Path(d)/'test.php';test.write_text(script)
            def check(seq,expected,expires=None,name='Hub'):
                m,s=signed(seq,expires,name)
                cmd=['php',str(test),str(PHP),base64.b64encode(m.encode()).decode(),base64.b64encode(s.encode()).decode(),pub,d,str(now)]
                result=subprocess.run(cmd,capture_output=True,text=True,check=True)
                self.assertEqual(result.stdout,expected,result.stderr)
            check(1,'OK');check(1,'OK');check(0,'REJECT');check(1,'REJECT',name='Altered');check(2,'OK');check(1,'REJECT');check(3,'REJECT',expires=now-1)
if __name__=='__main__': unittest.main()
