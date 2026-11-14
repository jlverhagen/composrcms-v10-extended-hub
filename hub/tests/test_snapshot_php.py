import json, pathlib, subprocess, tempfile, unittest, time
ROOT=pathlib.Path(__file__).resolve().parents[2]
PHP=ROOT/'cms/sources_custom/extended_catalogue_snapshot.php'
class SnapshotTests(unittest.TestCase):
 def run_php(self,s):
  r=subprocess.run(['php'],input='<?php\n'+s,text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stderr)
  return r.stdout
 def test_signed_staged_and_reused(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td); store=root/'store';store.mkdir(mode=0o700)
   code=f'''require '{PHP}';
    $pair=sodium_crypto_sign_keypair();$pub=base64_encode(sodium_crypto_sign_publickey($pair));
    $m=json_encode(['schema_version'=>1,'source_id'=>'test','issued_at'=>time()-1,'expires_at'=>time()+3600,'addons'=>[]]);
    $sig=json_encode(['algorithm'=>'Ed25519','key_id'=>'test-key','signature'=>base64_encode(sodium_crypto_sign_detached($m,sodium_crypto_sign_secretkey($pair)))]);
    file_put_contents('{root}/in.json',$m);file_put_contents('{root}/in.sig',$sig);
    $keys=['test-key'=>$pub];$ids=['test-key'];
    $a=extended_stage_signed_catalogue_snapshot('{root}/in.json','{root}/in.sig',$keys,$ids,'test','{store}');
    $b=extended_stage_signed_catalogue_snapshot('{root}/in.json','{root}/in.sig',$keys,$ids,'test','{store}');
    echo json_encode(['same'=>$a==$b,'exists'=>file_exists($a['manifest_path'])&&file_exists($a['signature_path'])]);'''
   data=json.loads(self.run_php(code));self.assertEqual(data,{'same':True,'exists':True})
 def test_existing_snapshot_conflict_preserves_stored_pair(self):
  with tempfile.TemporaryDirectory() as td:
   root = pathlib.Path(td)
   store = root / 'store'
   store.mkdir(mode=0o700)
   code = f"""require '{PHP}';
    $keypair = sodium_crypto_sign_keypair();
    $keys = ['test-key' => base64_encode(sodium_crypto_sign_publickey($keypair))];
    $now = time();
    $manifest = json_encode(['schema_version'=>1,'source_id'=>'test','issued_at'=>$now-1,'expires_at'=>$now+3600,'addons'=>[]]);
    $signature = json_encode(['algorithm'=>'Ed25519','key_id'=>'test-key','signature'=>base64_encode(sodium_crypto_sign_detached($manifest,sodium_crypto_sign_secretkey($keypair)))]);
    file_put_contents('{root}/in.json', $manifest);
    file_put_contents('{root}/in.sig', $signature);
    $stage = fn() => extended_stage_signed_catalogue_snapshot('{root}/in.json', '{root}/in.sig', $keys, ['test-key'], 'test', '{store}', $now);
    $snapshot = $stage();
    $oversized = str_repeat('x', 4097);
    file_put_contents($snapshot['signature_path'], $oversized);
    try {{ $stage(); throw new LogicException('Expected snapshot conflict'); }}
    catch (RuntimeException $e) {{ if ($e->getMessage() !== 'Snapshot conflict') throw $e; }}
    if (file_get_contents($snapshot['signature_path']) !== $oversized ||
        file_get_contents($snapshot['manifest_path']) !== $manifest) {{
        throw new LogicException('Existing snapshot changed');
    }}
    echo 'OK';"""
   self.assertEqual(self.run_php(code), 'OK')
 def test_wrong_identity_fails(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);store=root/'store';store.mkdir(mode=0o700)
   code=f'''require '{PHP}';
    $pair=sodium_crypto_sign_keypair();$pub=base64_encode(sodium_crypto_sign_publickey($pair));
    $m=json_encode(['schema_version'=>1,'source_id'=>'different','issued_at'=>time()-1,'expires_at'=>time()+3600,'addons'=>[]]);
    $sig=json_encode(['algorithm'=>'Ed25519','key_id'=>'test-key','signature'=>base64_encode(sodium_crypto_sign_detached($m,sodium_crypto_sign_secretkey($pair)))]);
    file_put_contents('{root}/in.json',$m);file_put_contents('{root}/in.sig',$sig);
    try {{ extended_stage_signed_catalogue_snapshot('{root}/in.json','{root}/in.sig',['test-key'=>$pub],['test-key'],'test','{store}');echo 'BAD';}} catch (RuntimeException $e) {{echo 'OK';}}'''
   self.assertEqual(self.run_php(code),'OK')
 def test_untrusted_signature_fails(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);store=root/'store';store.mkdir(mode=0o700)
   code=f'''require '{PHP}';
    $pair=sodium_crypto_sign_keypair();
    $m=json_encode(['schema_version'=>1,'source_id'=>'test','issued_at'=>time()-1,'expires_at'=>time()+3600,'addons'=>[]]);
    $sig=json_encode(['algorithm'=>'Ed25519','key_id'=>'untrusted','signature'=>base64_encode(sodium_crypto_sign_detached($m,sodium_crypto_sign_secretkey($pair)))]);
    file_put_contents('{root}/in.json',$m);file_put_contents('{root}/in.sig',$sig);
    try {{ extended_stage_signed_catalogue_snapshot('{root}/in.json','{root}/in.sig',[],[],'test','{store}');echo 'BAD';}} catch (RuntimeException $e) {{echo 'OK';}}'''
   self.assertEqual(self.run_php(code),'OK')

 def test_interrupted_pending_write_can_be_retried(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);store=root/'store';store.mkdir(mode=0o700)
   original=PHP.read_text()
   needle="                extended_registry_atomic_write($pending . '/catalogue.sig.json', $signature_bytes);"
   self.assertEqual(original.count(needle),1)
   # Inject a failure between the two writes without changing production behavior.
   code=original.replace('__DIR__',repr(str(PHP.parent))).replace(
       needle,"                if ($GLOBALS['interrupt']) throw new RuntimeException('Injected interruption');\n"+needle)
   harness=root/'snapshot.php';harness.write_text(code)
   script=f'''require '{harness}';
    $pair=sodium_crypto_sign_keypair();
    $keys=['key'=>base64_encode(sodium_crypto_sign_publickey($pair))];
    $now=time();
    $manifest=json_encode(['schema_version'=>1,'source_id'=>'test','issued_at'=>$now-1,'expires_at'=>$now+3600,'addons'=>[]]);
    $signature=json_encode(['algorithm'=>'Ed25519','key_id'=>'key','signature'=>base64_encode(sodium_crypto_sign_detached($manifest,sodium_crypto_sign_secretkey($pair)))]);
    file_put_contents('{root}/in.json',$manifest);file_put_contents('{root}/in.sig',$signature);
    $stage=fn()=>extended_stage_signed_catalogue_snapshot('{root}/in.json','{root}/in.sig',$keys,['key'],'test','{store}',$now);
    $interrupt=true;
    try {{ $stage(); throw new LogicException('Expected interruption'); }}
    catch (RuntimeException $e) {{ if ($e->getMessage() !== 'Injected interruption') throw $e; }}
    if (scandir('{store}') !== ['.','..','snapshots.lock']) throw new LogicException('Partial publication');
    $interrupt=false;
    $result=$stage();
    if (!is_file($result['manifest_path']) || !is_file($result['signature_path'])) throw new LogicException('Retry failed');
    echo 'OK';'''
   self.assertEqual(self.run_php(script),'OK')
