import pathlib, subprocess, unittest, tempfile, json, base64, time
ROOT = pathlib.Path(__file__).resolve().parents[2]
PHP = ROOT / 'cms' / 'sources_custom' / 'extended_addon_browser.php'

class BrowserPhpTests(unittest.TestCase):
    def call_php(self, script):
        r = subprocess.run(['php'], input='<?php\n'+script, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_empty_sources(self):
        output = self.call_php(f"require '{PHP}'; echo json_encode(extended_browser_load(['schema_version'=>1,'sources'=>[]]));")
        self.assertEqual(json.loads(output), {'sources': [], 'addons': []}) # PHP encodes empty arrays as []

    def test_reject_duplicate_source(self):
        output = self.call_php(f"require '{PHP}'; try {{ extended_browser_load(['schema_version'=>1,'sources'=>[['id'=>'x','enabled'=>false],['id'=>'x','enabled'=>false]]]); echo 'FAIL'; }} catch (RuntimeException $e) {{ echo 'OK'; }}")
        self.assertEqual(output,'OK')

    def test_html_escape(self):
        output = self.call_php(f"require '{PHP}'; echo extended_browser_render_html(['sources'=>[],'addons'=>[['id'=>'x','name'=>'<script>alert(1)</script>','source_id'=>'s','version'=>'1','license'=>'MIT','cms_minimum'=>'10.0.52','php_minimum'=>'8.2']]]);")
        self.assertNotIn('<script>',output)
        self.assertIn('&lt;script&gt;',output)

    def test_missing_enabled_source_fails_closed(self):
        output = self.call_php(f"require '{PHP}'; echo json_encode(extended_browser_load(['schema_version'=>1,'sources'=>[['id'=>'source','enabled'=>true]] ]));")
        data=json.loads(output)
        self.assertEqual(data['sources'][0]['status'],'unavailable')
        self.assertEqual(len(data['addons']),0)

    def test_two_signed_sources_and_collision(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            script = f'''require '{PHP}';
            $sources=[];
            foreach (['a','b'] as $id) {{
              $keys = sodium_crypto_sign_keypair();
              $pub = base64_encode(sodium_crypto_sign_publickey($keys));
              $manifest = ['schema_version'=>1,'source_id'=>$id,'issued_at'=>{int(time.time())-60},'expires_at'=>{int(time.time())+3600},'addons'=>[
                ['id'=>'shared','name'=>'Same addon','version'=>'1.0.0','download_url'=>'https://example.com/shared.tar','sha256'=>str_repeat('0',64),'license'=>'MIT','cms_compatibility'=>['major'=>10,'minimum'=>'10.0.52'],'php_compatibility'=>['minimum'=>'8.2']]
              ]];
              $bytes=json_encode($manifest,JSON_UNESCAPED_SLASHES);
              $sig=['algorithm'=>'Ed25519','key_id'=>'key-'.$id,'signature'=>base64_encode(sodium_crypto_sign_detached($bytes,sodium_crypto_sign_secretkey($keys)))];
              file_put_contents('{root}/'.$id.'.json',$bytes);
              file_put_contents('{root}/'.$id.'.sig',json_encode($sig));
              $sources[]=['id'=>$id,'enabled'=>true,'manifest_path'=>'{root}/'.$id.'.json','signature_path'=>'{root}/'.$id.'.sig','trusted_keys'=>['key-'.$id=>$pub],'allowed_key_ids'=>['key-'.$id]];
            }}
            echo json_encode(extended_browser_load(['schema_version'=>1,'sources'=>$sources]));'''
            output=self.call_php(script)
            data=json.loads(output)
            self.assertEqual(len(data['addons']),2)
            self.assertIn('a:shared',data['addons'])
            self.assertIn('b:shared',data['addons'])
            self.assertEqual([s['status'] for s in data['sources']],['verified','verified'])

    def test_expired_source_rejected(self):
        # Signed data is still rejected when expired.
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            script=f'''require '{PHP}';
                $keys=sodium_crypto_sign_keypair();
                $bytes=json_encode(['schema_version'=>1,'source_id'=>'a','issued_at'=>100,'expires_at'=>200,'addons'=>[]]);
                $sig=['algorithm'=>'Ed25519','key_id'=>'k','signature'=>base64_encode(sodium_crypto_sign_detached($bytes,sodium_crypto_sign_secretkey($keys)))];
                file_put_contents('{root}/a.json',$bytes);file_put_contents('{root}/a.sig',json_encode($sig));
                $source=['id'=>'a','enabled'=>true,'manifest_path'=>'{root}/a.json','signature_path'=>'{root}/a.sig','trusted_keys'=>['k'=>base64_encode(sodium_crypto_sign_publickey($keys))],'allowed_key_ids'=>['k']];
                echo json_encode(extended_browser_load(['schema_version'=>1,'sources'=>[$source]]));'''
            data=json.loads(self.call_php(script))
            self.assertEqual(data['sources'][0]['status'],'unavailable')
            self.assertEqual(len(data['addons']),0)

if __name__=='__main__': unittest.main()
