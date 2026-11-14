#!/usr/bin/env python3
"""Sign exact UTF-8 manifest bytes using Ed25519. Key is a 32-byte raw seed in a restricted file."""
import argparse,base64,json
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

def sign(manifest: bytes, seed: bytes, key_id: str):
    if len(seed)!=32 or not key_id or len(key_id)>128: raise ValueError('invalid signing key or key ID')
    key=Ed25519PrivateKey.from_private_bytes(seed)
    signature=key.sign(manifest)
    public=key.public_key().public_bytes(encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)
    return {'algorithm':'Ed25519','key_id':key_id,'signature':base64.b64encode(signature).decode('ascii')},base64.b64encode(public).decode('ascii')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--private-key',type=Path,required=True,help='32 raw bytes; never commit')
    p.add_argument('--key-id',required=True)
    p.add_argument('--signature-output',type=Path,required=True)
    args=p.parse_args()
    if args.signature_output.resolve()==args.manifest.resolve(): raise SystemExit('refusing to overwrite manifest')
    signature,public=sign(args.manifest.read_bytes(),args.private_key.read_bytes(),args.key_id)
    args.signature_output.write_text(json.dumps(signature,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    print('Public key (base64) for independent trust-store review:',public)
if __name__=='__main__':main()
