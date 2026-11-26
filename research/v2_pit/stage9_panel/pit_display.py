"""Read fiscal nine-month/full-year, entity-consolidated totals from the filed KIND body."""
import re
from lxml import html

from public_dart import normalized, table_rows
from stage82b.display_fields import (FIELDS, TITLE, UNIT_SCALES, compact, field_label,
    header_columns, kind_section, monetary_pair, table_metadata)


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
        if not all(exact for _,_,exact in periods):
            continue
        rows=table['rows']
        if len(rows)<2:
            continue
        lower={compact(c['text']) for c in rows[1]}
        if '3개월' in lower or '누적' in lower:
            if duration!=9 or not {'3개월','누적'}.issubset(lower):
                continue
            # Reuse the validated merged-header alignment, requesting only the YTD column.
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
                    result[name+'_'+side]=dict(status='exact_display_cumulative',value=value,table=i,row=j,
                        column=col,unit=unit,label=row[0]['text'])
    return result
