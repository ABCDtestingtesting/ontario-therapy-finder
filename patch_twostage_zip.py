from pathlib import Path
root=Path('package/Ontario_Therapy_Automated_Competition')
p=root/'google_auto.py';s=p.read_text()
a="                        'queries':len(pieces),'sources':[x['source_url'] for x in pieces],"
b=a+"\n                        'capped':any(x['capped'] for x in pieces),"
assert a in s;s=s.replace(a,b)
a="                    if val['missing_coordinates']:val['coverage']='unresolved_location_links'"
b="                    if val['missing_coordinates']:\n                        val['coverage']=('capped_with_unresolved_links' if val['capped'] else 'unresolved_location_links')"
assert a in s;s=s.replace(a,b);p.write_text(s)
p=root/'staged.py';s=p.read_text()
a="""        if row.get('status')!='completed' or row.get('coverage')!='observed_complete_feeds':continue
        if row.get('missing_coordinates') or row.get('google_count') is None:continue
        if row['google_count']>25:continue
        verified.append((row['google_count'],code))"""
b="""        if row.get('status')!='completed' or row.get('google_count') is None:continue
        coverage=row.get('coverage')
        if row.get('capped') or coverage not in ('observed_complete_feeds','unresolved_location_links'):continue
        missing=int(row.get('missing_coordinates') or 0)
        if missing<0 or missing>3:continue
        if coverage=='observed_complete_feeds' and missing:continue
        if coverage=='unresolved_location_links' and not missing:continue
        upper=row['google_count']+missing
        if upper>25:continue
        verified.append((upper,code))"""
assert a in s;s=s.replace(a,b);p.write_text(s)
