import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'publisher'))
from build_catalogue import build, inspect_tar, CatalogueError

class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def archive(self,name='addon.inf',content=b'name=example\n'):
        path=self.root/'example.tar'
        with tarfile.open(path,'w') as tar:
            info=tarfile.TarInfo(name)
            info.size=len(content)
            tar.addfile(info,io.BytesIO(content))
        return path
    def test_valid_archive(self):
        self.assertIn('name=example',inspect_tar(self.archive()))
    def test_reject_traversal(self):
        with self.assertRaises(CatalogueError):inspect_tar(self.archive('../addon.inf'))
    def test_reject_missing_inf(self):
        with self.assertRaises(CatalogueError):inspect_tar(self.archive('other.txt'))
    def test_reject_package_identity_mismatch_and_duplicates(self):
        entry={'id':'example','name':'Example','version':'1.0','download_url':'https://example.org/example.tar','license':'MIT','cms_compatibility':{'major':10,'minimum':'10.0.52'},'php_compatibility':{'minimum':'8.2'},'package_file':'example.tar'}
        for metadata in (b'name=other\n', b'name=example\nname=other\n', b'name="example\'\n'):
            with self.subTest(metadata=metadata):
                self.archive(content=metadata)
                from build_catalogue import validate_entry
                with self.assertRaisesRegex(CatalogueError, 'identity mismatch'):
                    validate_entry(entry, self.root)

    def test_reject_compressed_tar(self):
        path=self.root/'example.tar'
        with tarfile.open(path, 'w:gz') as tar:
            info=tarfile.TarInfo('addon.inf'); info.size=13
            tar.addfile(info,io.BytesIO(b'name=example\n'))
        with self.assertRaises(CatalogueError):
            inspect_tar(path)

    def test_tar_end_marker_and_padding(self):
        path = self.archive()
        block_size = tarfile.BLOCKSIZE
        zero_block = bytes(block_size)
        member = path.read_bytes()[:2 * block_size]
        valid = member + zero_block * 2
        for payload in (valid, valid + zero_block * 20):
            with self.subTest(valid_size=len(payload)):
                path.write_bytes(payload)
                self.assertEqual(inspect_tar(path), 'name=example\n')
        for payload, error in (
            (member, 'missing TAR end marker'),
            (member + zero_block, 'incomplete TAR end marker'),
            (member + zero_block + member, 'non-zero data after TAR end marker'),
            (valid + zero_block * 20 + member, 'non-zero data after TAR end marker'),
            (valid + b'\0', 'invalid tar size'),
        ):
            with self.subTest(error=error, size=len(payload)):
                path.write_bytes(payload)
                with self.assertRaisesRegex(CatalogueError, error):
                    inspect_tar(path)

    def test_valid_directory_and_multiblock_file(self):
        path = self.archive()
        with tarfile.open(path, 'a', format=tarfile.USTAR_FORMAT) as archive:
            directory = tarfile.TarInfo('assets')
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
            payload = b'\0' * 1025
            member = tarfile.TarInfo('assets/example.txt')
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        self.assertEqual(inspect_tar(path), 'name=example\n')

    def test_reject_tar_extension_headers(self):
        path = self.archive()
        with tarfile.open(path, 'a', format=tarfile.PAX_FORMAT) as archive:
            archive.addfile(tarfile.TarInfo('a' * 101))
        with self.assertRaisesRegex(CatalogueError, 'unsupported TAR entry type'):
            inspect_tar(path)

    def test_file_directory_collisions_in_both_orders(self):
        for entries in (('folder', 'folder/file'), ('folder/file', 'folder')):
            with self.subTest(entries=entries):
                path = self.archive()
                with tarfile.open(path, 'a') as tar:
                    for name in entries:
                        info = tarfile.TarInfo(name)
                        tar.addfile(info, io.BytesIO(b''))
                with self.assertRaisesRegex(CatalogueError, 'file is also a directory'):
                    inspect_tar(path)

    def test_catalogue_hash(self):
        self.archive()
        data={'schema_version':1,'source_id':'test','issued_at':1800000000,'expires_at':1800003600,'addons':[{'id':'example','name':'Example','version':'1.0.0','download_url':'https://example.org/example.tar','license':'MIT','cms_compatibility':{'major':10,'minimum':'10.0.52'},'php_compatibility':{'minimum':'8.2'},'package_file':'example.tar'}]}
        p=self.root/'input.json';p.write_text(json.dumps(data))
        result=build(p,self.root,now=1800000100)
        self.assertEqual(len(result['addons'][0]['sha256']),64)
        self.assertEqual((result['issued_at'], result['expires_at']), (1800000000, 1800003600))
        self.assertNotIn('package_file',result['addons'][0])

if __name__=='__main__':unittest.main()
