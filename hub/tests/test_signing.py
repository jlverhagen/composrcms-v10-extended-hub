import base64,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'publisher'))
from sign_manifest import sign
from merge_catalogues import merge
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
class SigningTests(unittest.TestCase):
 def test_signature_roundtrip(self):
  raw=b'{"schema_version":1,"source_id":"test","addons":[]}'
  envelope,public=sign(raw,bytes(range(32)),'test-key')
  Ed25519PublicKey.from_public_bytes(base64.b64decode(public)).verify(base64.b64decode(envelope['signature']),raw)
  with self.assertRaises(Exception):Ed25519PublicKey.from_public_bytes(base64.b64decode(public)).verify(base64.b64decode(envelope['signature']),raw+b' ')
 def test_reject_unapproved_source(self):
  registry={'sources':[{'id':'trusted','enabled':True,'priority':100}]}
  with self.assertRaises(ValueError):merge(registry,{'unknown':{'source_id':'unknown','schema_version':1,'addons':[]}})
 def test_preserve_colliding_ids_across_sources(self):
  registry={'sources':[{'id':'a','enabled':True,'priority':100},{'id':'b','enabled':True,'priority':50}]}
  catalogs={k:{'source_id':k,'schema_version':1,'addons':[{'id':'same','version':'1.0'}]} for k in ('a','b')}
  result=merge(registry,catalogs)
  self.assertEqual([(x['source_id'],x['id']) for x in result],[('a','same'),('b','same')])
 def test_registry_owns_merged_source_and_priority(self):
  registry={'sources':[{'id':'trusted','enabled':True,'priority':20}]}
  catalogs={'trusted':{'source_id':'trusted','schema_version':1,'addons':[
      {'id':'demo','source_id':'other','priority':5}]}}
  self.assertEqual(merge(registry,catalogs), [{'id':'demo','source_id':'trusted','priority':20}])
 def test_optional_registry_priority_defaults_to_zero(self):
  registry={'sources':[{'id':'trusted','enabled':True}]}
  catalogs={'trusted':{'source_id':'trusted','schema_version':1,'addons':[{'id':'demo'}]}}
  self.assertEqual(merge(registry,catalogs)[0]['priority'], 0)
 def test_reject_ambiguous_registry_sources_and_invalid_priority(self):
  catalogs={'trusted':{'source_id':'trusted','schema_version':1,'addons':[]}}
  source={'id':'trusted','enabled':True,'priority':1}
  with self.assertRaisesRegex(ValueError, 'duplicate registry source'):
   merge({'sources':[source, source | {'enabled':False}]}, catalogs)
  with self.assertRaisesRegex(ValueError, 'invalid registry priority'):
   merge({'sources':[source | {'priority':'1'}]}, catalogs)
if __name__=='__main__':unittest.main()
