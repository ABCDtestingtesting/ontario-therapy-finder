"""Generate audited FSA representatives using existing Statistics Canada polygons."""
import json
from finder import census
CODES="N4G P1P P2A K8A P1H N4W N4K L4R N8H P1L L9Y K6J K6V K8V N3Y N4N P8N P9N P4N P5N L6Z L7A N1T".split()
geos=census.fsa_geometry(print)
result={}
for fsa in CODES:
    if fsa not in geos:raise RuntimeError('Missing FSA '+fsa)
    lat,lon=census.representative(geos[fsa])
    result[fsa]=[round(lat,6),round(lon,6)]
print('CENTROIDS_JSON_START')
print(json.dumps(result,sort_keys=True))
print('CENTROIDS_JSON_END')
