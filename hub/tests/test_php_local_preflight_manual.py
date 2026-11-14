# Manual integration test: python hub/tests/test_php_local_preflight_manual.py
import subprocess,tempfile,tarfile,io,hashlib,json,time,base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
root=Path(__file__).resolve().parents[2]; cms=root/'cms/sources_custom'
def php(code):
 p=subprocess.run(['php','-d','display_errors=1','-r',code],capture_output=True,text=True);return p.returncode,p.stdout,p.stderr
def main():
    with tempfile.TemporaryDirectory() as t:
     t=Path(t); archive=t/'good.tar'
     with tarfile.open(archive,'w') as f:
      b=b'name="example"\nversion="1.0"\n';info=tarfile.TarInfo('addon.inf');info.size=len(b);f.addfile(info,io.BytesIO(b))
     h=hashlib.sha256(archive.read_bytes()).hexdigest()
     code=f'require {json.dumps(str(cms/"extended_addon_download.php"))}; echo json_encode(extended_verify_local_addon_package({json.dumps(str(archive))}, {json.dumps(h)}, "example"));'
     rc,out,err=php(code);print('valid TAR',rc,out,err);assert rc==0
     code=f'require {json.dumps(str(cms/"extended_addon_download.php"))}; extended_verify_local_addon_package({json.dumps(str(archive))}, {json.dumps("0"*64)}, "example");'
     rc,out,err=php(code);assert rc!=0;print('bad checksum rejected')
     archive=t/'bad.tar'
     with tarfile.open(archive,'w') as f:
      b=b'name="example"\n';info=tarfile.TarInfo('../escape');info.size=len(b);f.addfile(info,io.BytesIO(b))
     h=hashlib.sha256(archive.read_bytes()).hexdigest()
     code=f'require {json.dumps(str(cms/"extended_addon_download.php"))}; extended_verify_local_addon_package({json.dumps(str(archive))}, {json.dumps(h)}, "example");'
     rc,out,err=php(code);assert rc!=0;print('traversal rejected')
     seed=Ed25519PrivateKey.generate(); pub=seed.public_key().public_bytes(encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)
     now=int(time.time()); manifest={'schema_version':1,'source_id':'test','issued_at':now-100,'expires_at':now+1000,'addons':[]};m=json.dumps(manifest).encode(); (t/'m.json').write_bytes(m)
     (t/'sig.json').write_text(json.dumps({'algorithm':'Ed25519','key_id':'test-key','signature':base64.b64encode(seed.sign(m)).decode()}))
     code=f'require {json.dumps(str(cms/"extended_addon_catalogue.php"))}; $x=extended_verify_local_catalogue({json.dumps(str(t/"m.json"))}, {json.dumps(str(t/"sig.json"))}, ["test-key"=>{json.dumps(base64.b64encode(pub).decode())}], ["test-key"], "test"); echo $x["source_id"];'
     rc,out,err=php(code);print('signed manifest',rc,out,err);assert rc==0 and out=='test'
     code=code.replace('"test"); echo','"wrong"); echo');rc,out,err=php(code);assert rc!=0;print('wrong source rejected')
    print('all checks passed')


if __name__ == '__main__':
    main()
