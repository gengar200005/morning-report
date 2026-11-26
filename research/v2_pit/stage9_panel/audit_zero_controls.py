"""Exercise zero, nil, units, conflicting copies and cumulative contexts using a copy of a real XML file."""
from argparse import ArgumentParser
from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from hashlib import sha256
import json
from lxml import etree
from pit_facts import inspect_xbrl

SOURCE='035f4f8520be467f130ca656c87e206b1588525b0205cbb7f451e8ec5f700d5d'
FIELD='{http://xbrl.iasb.org/taxonomy/2010-04-30/ifrs}Revenue'


def run(package, output):
    raw=package.read_bytes()
    if sha256(raw).hexdigest()!=SOURCE:
        raise ValueError('wrong archived original')
    with ZipFile(BytesIO(raw)) as z:
        name,=[n for n in z.namelist() if n.endswith('.xbrl')]
        xml=z.read(name)
    end=date(2017,3,31)
    ref=inspect_xbrl(raw,'00154426',end)['3']['revenue_current']
    expected={'zero':(0,'exact_consolidated_quarter_fact'),'nil':(None,'nil_or_nonfinite'),
              'unknown_unit':(None,'unit_not_KRW'),'two_values':(None,'conflicting_values'),
              'six_month_period':(None,'no_supported_fact_in_exact_context')}
    observations={}
    for case,(want,status) in expected.items():
        root=etree.fromstring(xml)
        facts=[n for n in root if n.tag==FIELD and n.get('contextRef') in ref['contexts']]
        if len(facts)!=2:
            raise ValueError('expected two matching exact-context facts')
        for f in facts:
            if case=='zero':
                f.text='0'
            elif case=='nil':
                f.text=None
                f.set('{http://www.w3.org/2001/XMLSchema-instance}nil','true')
            elif case=='unknown_unit':
                f.set('unitRef','audit_unknown_unit')
        if case=='two_values':
            facts[0].text='17'
        if case=='six_month_period':
            for c in root:
                if c.get('id') in ref['contexts']:
                    start,=c.xpath('.//*[local-name()="startDate"]')
                    start.text='2016-10-01'
        target=BytesIO()
        with ZipFile(target,'w',compression=ZIP_DEFLATED) as z:
            z.writestr(name,etree.tostring(root,encoding='utf-8'))
        result=inspect_xbrl(target.getvalue(),'00154426',end)['3']['revenue_current']
        if (result.get('value'),result['status'])!=(want,status):
            raise ValueError((case,result,want,status))
        observations[case]={'value':result.get('value'),'status':result['status']}
    output.write_text(json.dumps({'modified_inputs_for_parser_controls_only':True,'source_sha256':SOURCE,'checks':observations},indent=2)+'\n')


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    p.add_argument('package',type=Path)
    p.add_argument('output',type=Path)
    run(**vars(p.parse_args()))
