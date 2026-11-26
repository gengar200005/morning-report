"""Reconcile a distinct wrapper hash by checking every embedded file of the same receipt."""
import argparse
import io
import json
import sqlite3
from pathlib import Path
from zipfile import ZipFile
from stage9_panel.collect_receipts import check_archive, once, sha

def members(raw):
    check_archive(raw)
    with ZipFile(io.BytesIO(raw)) as z:
        if len(z.namelist())!=len(set(z.namelist())):raise ValueError('duplicate archive member names')
        return {name:sha(z.read(name)) for name in sorted(z.namelist())}

def run(path,output):
    results=[]
    with sqlite3.connect(path,timeout=60) as db:
        db.execute('CREATE TABLE IF NOT EXISTS comparisons(receipt TEXT,kind TEXT,source TEXT,stored_sha TEXT,observed_sha TEXT,member_manifest TEXT,status TEXT,PRIMARY KEY(receipt,kind,observed_sha))')
        rows=db.execute("""SELECT p.receipt,p.kind,p.source,p.sha256,p.body FROM completed c JOIN packages p USING(receipt,kind)
                        WHERE p.kind='xbrl' AND (c.detail='conflicting immutable payload' OR EXISTS (SELECT 1 FROM quarantine q WHERE q.receipt=p.receipt AND q.kind=p.kind)) AND NOT EXISTS (SELECT 1 FROM comparisons t WHERE t.receipt=p.receipt AND t.kind=p.kind)""").fetchall()
        for rc,kind,url,first,body in rows:
            new_body=once(db,{'receipt':rc},kind,'wrapper_recheck','body',url,0.65)
            first_members,second_members=members(body),members(new_body)
            status='all_members_identical' if first_members==second_members else 'member_content_conflict'
            manifest=json.dumps(first_members,sort_keys=True)
            with db:
                db.execute('INSERT OR REPLACE INTO comparisons VALUES(?,?,?,?,?,?,?)',(rc,kind,url,first,sha(new_body),manifest,status))
                db.execute('INSERT OR IGNORE INTO quarantine VALUES(?,?,?)',(rc,kind,'second_original_observation_was_not_preserved'))
        for rc,kind,url,first,observed,manifest,status in db.execute('SELECT * FROM comparisons ORDER BY receipt'):
            files=json.loads(manifest)
            results.append(dict(receipt=rc,kind=kind,source=url,stored_sha256=first,rechecked_sha256=observed,
                                every_member_equal=status=='all_members_identical',member_count=len(files),
                                second_original_response='bytes_not_retained',member_manifest=files))
    output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('path','output'):p.add_argument(k,type=Path)
    run(**vars(p.parse_args()))
