"""Official 2021 Census sources, strict wide-column parser and paginated DA polygons.

Population = the 2021 baseline. A 5-km point estimate assumes uniform population
within each intersected dissemination area; estimates are labelled accordingly.
"""
from __future__ import annotations
import csv, io, re, math, json, zipfile, time, os, tempfile, shutil
from functools import lru_cache
from pathlib import Path
import requests
from shapely.geometry import shape, Point
from shapely.ops import transform
from pyproj import Transformer
from .common import DATA,SourceUnavailable,InvalidEvidence,write_json,read_json,sha256,valid_fsa
FSA_URL='https://www150.statcan.gc.ca/n1/tbl/csv/98100019-eng.zip'
DA_URL='https://www150.statcan.gc.ca/n1/tbl/csv/98100015-eng.zip'
GIS='https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Cartographic_boundary_files/MapServer'
FSA_LAYER=GIS+'/14/query'
DA_LAYER=GIS+'/12/query'
DA_BOUNDARY_ARCHIVES=(
 'https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/files-fichiers/lda_000b21a_e.zip',
 'https://data.source.coop/dataforcanada/d4c-datapkg-statistical/archive/statcan/boundaries/2021/lda_000b21a_e.zip')
UA='OntarioTherapyAreaResearch/5.1 census-geography'
FSA_BOUNDARY_ARCHIVES=(
 'https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/files-fichiers/lfsa000b21a_e.zip',
 'https://data.source.coop/dataforcanada/d4c-datapkg-statistical/archive/statcan/boundaries/2021/lfsa000b21a_e.zip')

@lru_cache(maxsize=1)
def project():return Transformer.from_crs(4326,3347,always_xy=True).transform
@lru_cache(maxsize=1)
def unproject():return Transformer.from_crs(3347,4326,always_xy=True).transform

def http_get(url, params=None, timeout=120, retries=4):
    errors=[]
    for i in range(retries):
        try:
            r=requests.get(url,params=params,timeout=(15,timeout),headers={'User-Agent':UA})
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            errors.append(str(exc))
            if i<retries-1:time.sleep(min(2**i,8))
    raise SourceUnavailable(f'{url} failed after {retries} attempts: {errors[-1]}')

def fetch_to_file(url,path, progress=None,retries=3):
    """Stream to temporary file and atomically commit only if download is complete."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    last=None
    for attempt in range(retries):
        tmp=None
        try:
            with requests.get(url,timeout=(15,120),stream=True,headers={'User-Agent':UA}) as r:
                r.raise_for_status()
                total=int(r.headers.get('Content-Length') or 0)
                with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as out:
                    tmp=Path(out.name);done=0;next_report=0
                    for chunk in r.iter_content(1024*512):
                        if not chunk:continue
                        out.write(chunk);done+=len(chunk)
                        if progress and done>=next_report:
                            progress(f'{path.name}: {done/1048576:.1f} MB'+(f' / {total/1048576:.1f} MB' if total else ''))
                            next_report=done+1024*1024
                    out.flush();os.fsync(out.fileno())
            if total and done!=total:raise InvalidEvidence(f'Download truncated: {done}/{total} bytes')
            if done<1000:raise InvalidEvidence('Download smaller than 1000 bytes')
            if not zipfile.is_zipfile(tmp):raise InvalidEvidence('Remote download is not a ZIP file')
            os.replace(tmp,path)
            return path
        except (requests.RequestException,OSError,InvalidEvidence) as exc:
            last=exc
            if tmp:tmp.unlink(missing_ok=True)
            if attempt<retries-1:time.sleep(min(2**attempt,10))
    raise SourceUnavailable(f'{url}: failed download after retries: {last}')

def column_map(columns):
    fields={}
    for c in columns:
        s=' '.join(c.lower().split())
        if 'population and dwelling counts' not in s:continue
        if re.search(r'population,\s*2021\b',s) and 'change' not in s and 'percent' not in s:fields['population']=c
        elif 'private dwellings occupied by usual residents' in s and '2021' in s:fields['occupied']=c
        elif 'total private dwellings' in s and '2021' in s:fields['dwellings']=c
    return fields

def as_int(v):
    s=str(v or '').strip().replace(',','')
    return int(s) if re.fullmatch(r'\d+',s) else None

def parse_zip(path,kind,min_rows=None):
    """Real StatCan 2021 census downloads are transposed (characteristics as columns).
    Reject unexpected schemas, suppressed counts, impossible numbers and sparse downloads.
    """
    if kind not in ('fsa','da'):raise ValueError(kind)
    threshold=min_rows if min_rows is not None else (300 if kind=='fsa' else 10000)
    results={};csv_found=False;skipped=0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.lower().endswith('.csv') or 'metadata' in name.lower():continue
            with z.open(name) as raw:
                reader=csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig',newline=''))
                cols=reader.fieldnames or []
                if 'GEO' not in cols:continue
                fields=column_map(cols)
                if 'population' not in fields or 'occupied' not in fields:
                    raise InvalidEvidence(f'Unexpected StatCan {kind} CSV schema: {cols[:9]}')
                csv_found=True
                for row in reader:
                    if kind=='fsa':
                        match=re.search(r'\b([KLMNP]\d[A-Z])\b',str(row.get('GEO','')).upper())
                        uid=match.group(1) if match else None
                    else:
                        dguid=str(row.get('DGUID',''))
                        match=re.search(r'2021S0512(35\d{6})$',dguid)
                        if not match:match=re.search(r'(?<!\d)(35\d{6})(?!\d)',str(row.get('GEO','')))
                        uid=match.group(1) if match else None
                    if not uid:continue
                    pop=as_int(row.get(fields['population']));occ=as_int(row.get(fields['occupied']))
                    dw=as_int(row.get(fields['dwellings'])) if 'dwellings' in fields else None
                    if pop is None or occ is None or (dw is not None and dw<occ):
                        skipped+=1;continue
                    if uid in results:
                        if results[uid]['population']!=pop:raise InvalidEvidence('Conflicting duplicate '+uid)
                        continue
                    results[uid]={'population':pop,'occupied':occ,'dwellings':dw}
    if not csv_found:raise InvalidEvidence(f'No census CSV found in {path}')
    if len(results)<threshold:raise InvalidEvidence(f'Incomplete census {kind} records: {len(results)} < {threshold}; skipped {skipped}')
    return results

def load_population(kind,progress=None):
    target=DATA/f'{kind}_population.json'
    if target.exists():
        cached=read_json(target)
        if len(cached)>=(300 if kind=='fsa' else 10000):return cached
        target.unlink()
    archive=DATA/'downloads'/f'{kind}_source.zip'
    if not archive.exists():fetch_to_file(FSA_URL if kind=='fsa' else DA_URL,archive,progress)
    if progress:progress(f'Parsing {kind.upper()} 2021 census rows')
    try:records=parse_zip(archive,kind)
    except Exception:
        # Remove corrupt/unexpected archives to force a clean download on resume.
        archive.rename(archive.with_suffix('.invalid.zip'))
        raise
    write_json(target,records)
    write_json(DATA/f'{kind}_provenance.json',{'url':FSA_URL if kind=='fsa' else DA_URL,
                          'source_sha256':sha256(archive),'records':len(records),'census_year':2021})
    return records

def _arc_json(url,params):
    try:reply=json.loads(http_get(url,params).decode('utf8'))
    except (ValueError,UnicodeDecodeError) as ex:raise InvalidEvidence(f'Invalid ArcGIS JSON: {ex}')
    if not isinstance(reply,dict) or 'error' in reply:raise SourceUnavailable(f'ArcGIS query returned {str(reply)[:500]}')
    return reply

def _envelope_params(bbox):
    return {'geometry':','.join(f'{x:.7f}' for x in bbox),'geometryType':'esriGeometryEnvelope',
            'inSR':'4326','spatialRel':'esriSpatialRelIntersects'} if bbox else {}

def load_layer(url,where,field,bbox=None,progress=None):
    """Retrieve all ArcGIS geometries, splitting failed pages deterministically.

    A geometry-heavy request can return HTTP 500 on Statistics Canada's ArcGIS
    server despite a working service. Retry the *same* offset in smaller chunks;
    never move past a failed or empty page or treat a partial set as complete.
    """
    p={'where':where,'returnCountOnly':'true','f':'json',**_envelope_params(bbox)}
    expected=_arc_json(url,p).get('count')
    if not isinstance(expected,int) or expected<1:
        raise InvalidEvidence(f'ArcGIS returned invalid count: {expected}')
    seen={};offset=0;limit=150
    while offset<expected:
        size=min(limit,expected-offset)
        # Track failures. One overly complex boundary can make a batch fail,
        # so recursively halve *that exact batch* and preserve every record.
        def get_page(start,count):
            params={'where':where,'outFields':'*','returnGeometry':'true',
                    'outSR':'4326','f':'geojson','orderByFields':'OBJECTID ASC',
                    'resultOffset':start,'resultRecordCount':count,
                    **_envelope_params(bbox)}
            try:
                page=_arc_json(url,params)
                if page.get('type')!='FeatureCollection' or not isinstance(page.get('features'),list):
                    raise InvalidEvidence('ArcGIS did not return GeoJSON FeatureCollection')
                items=page['features']
                if not items:
                    raise InvalidEvidence(f'ArcGIS returned empty page at {start}/{expected}')
                if len(items)>count:
                    raise InvalidEvidence(f'ArcGIS returned too many geometries at {start}: {len(items)}/{count}')
                return items
            except (SourceUnavailable,InvalidEvidence) as exc:
                # An actual empty page is evidence of a missing offset; never
                # skip it. For a large request we can still retry subranges.
                if count<=1:
                    # ArcGIS can reject one complex raw polygon. Limited
                    # generalization reduces payload without omitting the area.
                    for precision in (0.00005,0.0002,0.001):
                        try:
                            alternative=_arc_json(url,{**params,'maxAllowableOffset':precision})
                            features=alternative.get('features',[])
                            if alternative.get('type')=='FeatureCollection' and len(features)==1:
                                return features
                        except (SourceUnavailable,InvalidEvidence):pass
                    if isinstance(exc,InvalidEvidence):raise
                    raise SourceUnavailable(f'ArcGIS failed single geometry at offset {start} for {field}: {exc}') from exc
                half=count//2
                if progress:progress(f'ArcGIS heavy geometry at {start}; retrying {half}+{count-half} records')
                return get_page(start,half)+get_page(start+half,count-half)
        items=get_page(offset,size)
        for feat in items:
            properties=feat.get('properties') or {}
            key=str(properties.get(field) or '')
            geometry=feat.get('geometry')
            if not key or not geometry or key in seen:
                raise InvalidEvidence(f'Duplicate or missing geometry {key} at offset {offset}')
            g=shape(geometry)
            if not g.is_valid:g=g.buffer(0)
            if g.is_empty or g.area<=0:
                raise InvalidEvidence(f'Invalid geometry for {key}')
            seen[key]=g.__geo_interface__
        offset+=len(items)
        if progress:progress(f'{field} boundaries: {offset}/{expected} verified')
    if len(seen)!=expected:
        raise InvalidEvidence(f'{field} count mismatch {len(seen)}/{expected}')
    return seen

def _parse_fsa_shapefile_archive(archive,minimum=300):
    """Use official, projected 2021 FSA shapefiles when ArcGIS requests fail.

    Only the known .shp/.shx/.dbf files are extracted, to trusted local names.
    Preserve original source provenance and validate Ontario geometry/count.
    """
    import shapefile
    archive=Path(archive)
    root=DATA/'downloads'/'fsa_extracted'
    root.mkdir(parents=True,exist_ok=True)
    prefix=root/'source_fsa'
    with zipfile.ZipFile(archive) as zipped:
        shape_files=[name for name in zipped.namelist() if name.lower().endswith('.shp')]
        if len(shape_files)!=1:raise InvalidEvidence('Expected one FSA shapefile in verified census archive')
        base=shape_files[0][:-4]
        for ext in ('.shp','.shx','.dbf'):
            item=next((n for n in zipped.namelist() if n.lower()==(base+ext).lower()),None)
            if not item:raise InvalidEvidence(f'FSA shapefile missing {ext}')
            with zipped.open(item) as inp,(prefix.with_suffix(ext)).open('wb') as out:
                shutil.copyfileobj(inp,out)
    results={}
    with shapefile.Reader(str(prefix),encoding='latin1') as reader:
        columns=[x[0] for x in reader.fields[1:]]
        if 'CFSAUID' not in columns:raise InvalidEvidence('Expected CFSAUID in census shapefile')
        for rec in reader.iterShapeRecords():
            item=dict(zip(columns,rec.record))
            code=str(item.get('CFSAUID') or '').strip().upper()
            if not valid_fsa(code):continue
            g=transform(unproject(),shape(rec.shape.__geo_interface__))
            if not g.is_valid:g=g.buffer(0)
            if g.is_empty or g.area<=0:raise InvalidEvidence(f'Bad FSA shape from archive: {code}')
            if code in results:raise InvalidEvidence(f'Duplicate archived Ontario FSA: {code}')
            point=g.representative_point()
            if not (41<point.y<57 and -96<point.x<-73):
                raise InvalidEvidence(f'Wrong FSA boundary projection: {code}')
            results[code]=g.__geo_interface__
    if len(results)<minimum:
        raise InvalidEvidence(f'Archived Ontario FSA count {len(results)} < {minimum}')
    return results


def _fsa_archive_fallback(progress=None):
    archive=DATA/'downloads'/'lfsa000b21a_e.zip'
    errors=[];source=None
    if archive.exists() and zipfile.is_zipfile(archive):
        return _parse_fsa_shapefile_archive(archive)
    for uri in FSA_BOUNDARY_ARCHIVES:
        try:
            if progress:progress('Trying full official FSA geometry archive (fallback)')
            fetch_to_file(uri,archive,progress,retries=1)
            regions=_parse_fsa_shapefile_archive(archive)
            source=uri
            write_json(DATA/'fsa_archive_provenance.json',
                       {'url':source,'sha256':sha256(archive),'count':len(regions)})
            return regions
        except (SourceUnavailable,InvalidEvidence,zipfile.BadZipFile,ValueError,OSError) as exc:
            errors.append(f'{uri}: {exc}')
            archive.unlink(missing_ok=True)
    raise SourceUnavailable('All official FSA geometry sources failed: '+'; '.join(errors))

def fsa_geometry(progress=None):
    target=DATA/'fsa_boundaries.json'
    if target.exists():
        try:
            data=read_json(target)
            if isinstance(data,dict) and len(data)>=300 and all(
                    valid_fsa(code) and isinstance(geom,dict) and
                    not shape(geom).is_empty and shape(geom).area>0
                    for code,geom in data.items()):
                return data
        except (ValueError,TypeError,KeyError,AttributeError):
            pass
        if progress:progress('Cached census boundaries failed geometry validation; downloading verified source')
        target.unlink(missing_ok=True)
    try:
        # The official archive is more reliable than querying hundreds of
        # national polygons through the rate-limited ArcGIS geometry service.
        # Prefer the complete archive and independently validate all Ontario
        # identifiers and geometries before accepting it.
        polys=_fsa_archive_fallback(progress)
    except (SourceUnavailable,InvalidEvidence,zipfile.BadZipFile,OSError) as archive_error:
        if progress:progress(f'Census boundary archive unavailable ({archive_error}); retrying ArcGIS geometry service')
        polys=load_layer(FSA_LAYER,"PRUID='35'",'CFSAUID',progress=progress)
    if len(polys)<300 or any(not valid_fsa(x) for x in polys):raise InvalidEvidence('Ontario FSA boundaries invalid')
    write_json(target,polys);return polys

def representative(geometry):
    p=shape(geometry).representative_point();return (round(p.y,6),round(p.x,6))

def _parse_da_shapefile_archive(archive,bbox,progress=None):
    """Return Ontario DAs intersecting a lon/lat envelope from 2021 CBF.

    Verify the full zipped national file and inspect records before using any
    filtered geometries. Materialize only trusted shapefile components; the
    archive is reused across nearby FSA searches, not downloaded repeatedly.
    """
    import shapefile
    archive=Path(archive)
    root=DATA/'downloads'/'da_extracted'
    prefix=root/'source_da'
    root.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        shapes=[n for n in zipped.namelist() if n.lower().endswith('.shp')]
        if len(shapes)!=1:raise InvalidEvidence('Expected one DA shapefile in verified census archive')
        base=shapes[0][:-4]
        for ext in ('.shp','.shx','.dbf'):
            member=next((n for n in zipped.namelist() if n.lower()==(base+ext).lower()),None)
            if not member:raise InvalidEvidence(f'DA shapefile missing {ext}')
            outpath=prefix.with_suffix(ext)
            if not outpath.exists() or outpath.stat().st_size!=zipped.getinfo(member).file_size:
                tmp=outpath.with_suffix(ext+'.partial')
                try:
                    with zipped.open(member) as inp,tmp.open('wb') as out:shutil.copyfileobj(inp,out)
                    os.replace(tmp,outpath)
                finally:tmp.unlink(missing_ok=True)
    # Conservative preliminary bounds in EPSG:3347, with margin for nonlinear
    # projections. Every candidate is checked again in true lon/lat geometry.
    from shapely.geometry import box
    projected_envelope=transform(project(),box(*bbox)).buffer(2500).bounds
    west,south,east,north=projected_envelope
    wanted=box(*bbox)
    results={}
    with shapefile.Reader(str(prefix),encoding='latin1') as reader:
        cols=[x[0] for x in reader.fields[1:]]
        if 'DAUID' not in cols or len(reader)<20000:
            raise InvalidEvidence('DA shapefile is missing identifiers or has too few national records')
        id_index=cols.index('DAUID')
        for index,record in enumerate(reader.iterRecords()):
            code=str(record[id_index] or '').strip()
            if not re.fullmatch(r'35\d{6}',code):continue
            feature=reader.shape(index)
            bounds=feature.bbox
            if not bounds or bounds[2]<west or bounds[0]>east or bounds[3]<south or bounds[1]>north:
                continue
            g=transform(unproject(),shape(feature.__geo_interface__))
            if not g.is_valid:g=g.buffer(0)
            if g.is_empty or g.area<=0:raise InvalidEvidence(f'Invalid DA archive geometry: {code}')
            if not g.intersects(wanted):continue
            if code in results:raise InvalidEvidence(f'Duplicate DA in official archive: {code}')
            p=g.representative_point()
            if not (41<p.y<57 and -96<p.x<-73):
                raise InvalidEvidence(f'Incorrect DA archive projection: {code}')
            results[code]=g.__geo_interface__
    if not results:raise InvalidEvidence(f'Official DA archive found no Ontario DA boundaries in {bbox}')
    if progress:progress(f'Validated {len(results)} DA geometries from full 2021 Statistics Canada archive')
    return results


def _da_archive_fallback(bbox,progress=None):
    archive=DATA/'downloads'/'lda_000b21a_e.zip'
    errors=[]
    # An existing archive is reused, but always pass its shapefile validations.
    if archive.exists() and zipfile.is_zipfile(archive):
        try:return _parse_da_shapefile_archive(archive,bbox,progress)
        except (InvalidEvidence,ValueError,OSError,zipfile.BadZipFile) as exc:
            if progress:progress(f'Invalid cached DA archive: {exc}; downloading clean copy')
            archive.unlink(missing_ok=True)
    for uri in DA_BOUNDARY_ARCHIVES:
        try:
            if progress:progress('Downloading official 2021 dissemination-area boundaries after ArcGIS failure')
            fetch_to_file(uri,archive,progress,retries=1)
            result=_parse_da_shapefile_archive(archive,bbox,progress)
            write_json(DATA/'da_archive_provenance.json',
                       {'url':uri,'sha256':sha256(archive),'national_archive':'lda_000b21a_e.zip',
                        'selected_ontario_das':len(result),'census_year':2021})
            return result
        except (SourceUnavailable,InvalidEvidence,zipfile.BadZipFile,ValueError,OSError) as exc:
            errors.append(f'{uri}: {exc}')
            archive.unlink(missing_ok=True)
    raise SourceUnavailable('DA official archive unavailable: '+'; '.join(errors))


def da_near(fsa,geom,progress=None,pad_km=6.2):
    target=DATA/'da_boundaries'/f'{fsa}.json'
    if target.exists():
        data=read_json(target)
        if data:return data
    g=transform(project(),shape(geom)).buffer(pad_km*1000)
    lonlat=transform(unproject(),g)
    try:
        found=load_layer(DA_LAYER,"PRUID='35'",'DAUID',bbox=lonlat.bounds,progress=progress)
    except (SourceUnavailable,InvalidEvidence) as arc_error:
        if progress:progress(f'DA ArcGIS incomplete ({arc_error}); using official 2021 archive')
        found=_da_archive_fallback(lonlat.bounds,progress)
    if not found:raise InvalidEvidence(f'No verified DA boundaries for {fsa}')
    write_json(target,found)
    return found

def catchment(lat,lon,geometries,population,radius_km=5):
    target=transform(project(),Point(lon,lat)).buffer(radius_km*1000,quad_segs=32)
    people=homes=0.0;intersections=0;missing=[]
    for code,poly in geometries.items():
        geom=transform(project(),shape(poly))
        if not geom.is_valid:geom=geom.buffer(0)
        if geom.area==0 or not geom.intersects(target):continue
        if code not in population:missing.append(code);continue
        weight=min(1,geom.intersection(target).area/geom.area)
        people+=population[code]['population']*weight
        homes+=population[code]['occupied']*weight
        intersections+=1
    if missing:raise InvalidEvidence(f'Missing population data for intersecting DAs {missing[:12]}')
    if intersections==0 or people<=0:raise InvalidEvidence(f'Missing positive population within {radius_km} km')
    return {'population_2021_estimate':round(people),'occupied_dwellings_2021_estimate':round(homes),
            'intersected_da':intersections,'radius_km':radius_km,
            'assumption':'Population uniform within each 2021 dissemination-area polygon'}

def areas_near_hamilton(radius_km=125,min_population=12000,exclude_within_km=11):
    from .rank import haversine
    pop=load_population('fsa');geom=fsa_geometry(); found=[]
    for code,g in geom.items():
        if code not in pop or pop[code]['population']<min_population:continue
        lat,lon=representative(g);distance=haversine((43.2557,-79.8711),(lat,lon))
        if exclude_within_km<=distance<=radius_km:
            found.append({'fsa':code,'population_2021':pop[code]['population'],
                          'occupied_dwellings_2021':pop[code]['occupied'],
                          'distance_from_hamilton_km':round(distance,1),'lat':lat,'lon':lon})
    return sorted(found,key=lambda a:(a['distance_from_hamilton_km'],a['fsa']))
