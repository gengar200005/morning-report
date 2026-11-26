from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import authenticated_sample as app

DUMMY = 'z'*40


def fixture_listing(key,corp,start,end,category):
    sample = [s for s in app.SAMPLE if s[0]==corp and s[1].startswith(start[:4])][0]
    receipts = sample[2 if category=='A' else 3]
    rows = [dict(rcept_no=n,corp_code=corp,rcept_dt=n[:8],
                 report_nm=('[기재정정]' if i else '') + ('분기보고서' if category=='A' else '연결영업(잠정)실적'))
            for i,n in enumerate(receipts)]
    return [json.dumps({'status':'000' if rows else '013','list':rows}).encode()]


def fixture_zip(key,endpoint,**params):
    stream = io.BytesIO()
    with ZipFile(stream,'w') as z:
        ext = 'xml' if endpoint=='document.xml' else 'xbrl'
        z.writestr(params['rcept_no']+'.'+ext,b'<fixture/>')
    return stream.getvalue()


class AuthSampleTest(unittest.TestCase):
    def setUp(self):
        refs = {(corp,r):sha256(b'<fixture/>').hexdigest() for corp,_,reports,_ in app.SAMPLE for r in reports}
        self.reference = patch.object(app,'public_reference',return_value=refs).start()
        self.addCleanup(patch.stopall)

    def test_missing_key_and_non_echo_prompt_failure(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ,{},clear=True), patch.object(app,'listing') as listing:
            target=Path(folder)/'new'
            with redirect_stdout(io.StringIO()) as out, patch.object(app,'getpass',side_effect=app.GetPassWarning):
                self.assertEqual(app.main([str(target),'--prompt-key']),2)
            self.assertEqual(json.loads(out.getvalue())['api_called'],False)
            listing.assert_not_called()
            self.assertFalse(target.exists())

    @patch.object(app,'archive',side_effect=fixture_zip)
    @patch.object(app,'listing',side_effect=fixture_listing)
    def test_full_sample_and_resume(self,listing,archive):
        with TemporaryDirectory() as folder:
            directory=Path(folder)
            result=app.run(DUMMY,directory)
            self.assertEqual(result['status'],'PASS')
            self.assertEqual(result['public_instance_matches'],9)
            self.assertEqual(len(result['receipts']),19)
            self.assertEqual(len({r['receipt'] for r in result['receipts']}),19)
            self.assertEqual(sum(r['version']=='correction' for r in result['receipts']),5)
            self.assertEqual(listing.call_count,16)
            self.assertEqual(archive.call_count,28)
            self.assertEqual(app.run(DUMMY,directory),result)
            self.assertEqual(archive.call_count,28)
            self.assertEqual(listing.call_count,16)
            with sqlite3.connect(directory/'api_archive.sqlite3') as db:
                db.execute("UPDATE archive SET body=x'00' WHERE name='20210517001185-document.zip'")
            repeat=app.run(DUMMY,directory)
            self.assertEqual(repeat['status'],'BLOCKED')
            self.assertEqual(repeat['receipts'][0]['files']['document']['status'],'BLOCKED')

    def test_zip_repacking_and_instance_mismatch_are_separate(self):
        sample=app.SAMPLE[0]
        key=(sample[0],sample[2][0])
        ref=self.reference.return_value
        original=fixture_zip(DUMMY,'fnlttXbrl.xml',rcept_no=key[1])
        stream=io.BytesIO()
        with ZipFile(stream,'w') as z:
            z.writestr('different-envelope.xbrl',b'<fixture/>')
        self.assertNotEqual(original,stream.getvalue())
        self.assertEqual(app.instance_comparison(stream.getvalue(),ref[key])['status'],'PASS')
        ref[key]='0'*64
        with TemporaryDirectory() as folder, patch.object(app,'archive',side_effect=fixture_zip), patch.object(app,'listing',side_effect=fixture_listing):
            result=app.run(DUMMY,Path(folder))
            self.assertEqual(result['status'],'BLOCKED')
            self.assertEqual(result['acquisition_status'],'PASS')
            self.assertEqual(result['public_instance_matches'],8)
            first=result['receipts'][0]
            self.assertEqual(first['instance_comparison']['status'],'FAIL')
            self.assertEqual(first['files']['xbrl']['status'],'PASS')

    def test_partial_failure_retries_only_missing_archive(self):
        with TemporaryDirectory() as folder, patch.object(app,'listing',side_effect=fixture_listing):
            def fail_one(key,endpoint,**params):
                if params['rcept_no']=='20161130001119' and endpoint=='document.xml':
                    raise ValueError('sensitive URL '+key)
                return fixture_zip(key,endpoint,**params)
            directory=Path(folder)
            with patch.object(app,'archive',side_effect=fail_one):
                result=app.run(DUMMY,directory)
                self.assertEqual(result['status'],'BLOCKED')
                self.assertNotIn(DUMMY,json.dumps(result))
            with patch.object(app,'archive',side_effect=fixture_zip) as retry:
                self.assertEqual(app.run(DUMMY,directory)['status'],'PASS')
                retry.assert_called_once_with(DUMMY,'document.xml',rcept_no='20161130001119')

    def test_wrong_version_or_sensitive_payload_not_archived(self):
        def wrong_version(*args):
            page = json.loads(fixture_listing(*args)[0])
            for row in page['list']:
                row['report_nm'] = row['report_nm'].replace('[기재정정]', '')
            return [json.dumps(page).encode()]
        def leaked(key,endpoint,**params):
            b=io.BytesIO()
            with ZipFile(b,'w') as z: z.writestr('filing.xml',key)
            return b.getvalue()
        with TemporaryDirectory() as folder, patch.object(app,'listing',side_effect=wrong_version), patch.object(app,'archive',side_effect=leaked):
            path=Path(folder)
            result=app.run(DUMMY,path)
            self.assertEqual(result['status'],'BLOCKED')
            self.assertTrue(any(r.get('reason')=='LIST_IDENTITY_TYPE_OR_VERSION_UNCONFIRMED' and
                                r['version']=='correction' for r in result['receipts']))
            with sqlite3.connect(path/'api_archive.sqlite3') as db:
                self.assertEqual(db.execute("SELECT count(*) FROM archive WHERE name LIKE '%.zip'").fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
