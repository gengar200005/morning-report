"""Read fiscal nine-month/full-year, entity-consolidated totals from the filed KIND body."""
import re
from lxml import html

from public_dart import normalized, table_rows
from stage82b.display_fields import (FIELDS, TITLE, UNIT_SCALES, compact, field_label,
    fiscal_key, header_columns, kind_section, monetary_pair, table_metadata)


def labelled_columns(rows, periods, wanted, duration):
    """Match an explicitly numbered standalone fiscal quarter beside its YTD column."""
    suffix='(검토받지않은재무제표)'
    labels=[compact(c['text']).removesuffix(suffix) for c in rows[1]]
    positions=[int(c.get('rowspan',1))>1 for c in rows[0]]
    if positions!=sorted(positions,reverse=True):
        return None
    projected=[{**c,'text':'3개월' if re.fullmatch(r'[당전][1-4]분기',v) else 'skip'} for c,v in zip(rows[1],labels)]
    groups=header_columns([rows[0],projected],periods)
    if not groups:
        return None
    both=[]
    for side,(key,start,_),(_,end) in zip(('당','전'),periods,wanted,strict=True):
        months=(end.year-start.year)*12+end.month-start.month+1
        if months not in (3,6,9,12) or not key.endswith(str(months//3)+'분기'):
            return None
        label=side+str(months//3)+'분기'
        upper=[c for c in rows[0] if fiscal_key(c['text'])==key]
        if labels.count(label)!=1 or len(upper)!=1 or int(upper[0].get('colspan',1))!=2:
            return None
        index=0 if side=='당' else 1
        numeric_offset=sum(int(c.get('colspan',1)) for c in rows[0] if int(c.get('rowspan',1))>1)
        # The numbered column and its YTD sibling must be adjacent in the lower header.
        cell=groups[index][0]-numeric_offset
        if cell<0 or labels[cell:cell+2]!=[label,'누적']:
            return None
        both.append([groups[index][0]+(duration==9)])
    return both


def cumulative_facts(raw, duration, wanted):
    tree = html.fromstring(raw.decode('utf-8'))
    pattern = r'\d+\.\s*연결재무제표'
    heads = [normalized(s) for s in tree.xpath('//a[@name]/text()') if re.fullmatch(pattern, normalized(s))]
    if len(heads)==1:
        section,label=raw,heads[0]
    else:
        section,label=kind_section(tree,pattern)
    if not section:
        return {}
    try:
        tables=table_rows(section,label)
    except ValueError as error:
        if 'no display tables' not in str(error):
            raise
        return {}
    result={}
    seen=set()
    for i,table in enumerate(tables[1:],1):
        meta=tables[i-1]
        if i>=2 and len(tables[i-2]['rows'])==1 and len(tables[i-2]['rows'][0])==1:
            label=tables[i-2]['rows'][0][0]['text']
            if TITLE.fullmatch(compact(label)):
                meta={**meta,'rows':[[{'text':label}]]+meta['rows']}
        match=table_metadata(meta,'CFS',wanted)
        if not match:
            continue
        unit,periods=match
        if duration!=3 and not all(exact for _,_,exact in periods):
            continue
        rows=table['rows']
        if len(rows)<2:
            continue
        lower={compact(c['text']) for c in rows[1]}
        numbered=any(re.fullmatch(r'[당전][1-4]분기(?:\(검토받지않은재무제표\))?',v) for v in lower)
        if numbered:
            if duration not in (3,9):
                continue
            columns=labelled_columns(rows,periods,wanted,duration)
        elif duration==3:
            continue  # The primary display parser already reads standard three-month labels.
        elif '3개월' in lower or '누적' in lower:
            if duration!=9 or not {'3개월','누적'}.issubset(lower):
                continue
            sub=[{**col,'text':{'누적':'3개월','3개월':'skip'}.get(compact(col['text']),col['text'])} for col in rows[1]]
            columns=header_columns([rows[0],sub],periods)
        else:
            columns=header_columns(rows,periods)
        if not columns:
            continue
        for name,allowed in FIELDS.items():
            matches=[(j,r) for j,r in enumerate(rows) if r and field_label(r[0]['text']) in allowed]
            if not matches:
                continue
            if name in seen or len(matches)!=1:
                for side in ('current','prior'):
                    result[name+'_'+side]={'status':'ambiguous_display_rows'}
                seen.add(name)
                continue
            seen.add(name)
            j,row=matches[0]
            try:
                amounts=monetary_pair(row,columns,UNIT_SCALES[unit])
            except ValueError:
                continue
            if amounts:
                for side,(col,_,value) in zip(('current','prior'),amounts,strict=True):
                    result[name+'_'+side]=dict(status='exact_display_fiscal_quarter' if duration==3 else 'exact_display_cumulative',value=value,table=i,row=j,
                        column=col,unit=unit,label=row[0]['text'],source_headers=[c['text'] for c in rows[1]] if numbered else [])
    return result
