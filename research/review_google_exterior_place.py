"""Human-reviewable exterior Google place exception with primary-source proof.

The Google place link below does not expose coordinates in its canonical URL.
Its uniquely named practitioner publicly identifies one in-person office in
Ingersoll, more than 60 km from the 5-km N0L reference. This adjudication
never invents Google coordinates or drops the original place link.
"""
from __future__ import annotations
import math

PLACE_KEY = "0x131ec0f0e46a697:0x99076c9617b15499"
PLACE_NAME = "Cindy Machado @ Machado Psychotherapy"
PRIMARY_SOURCE = "https://www.ingersollwellness.ca/cindy"
BOOKING_SOURCE = "https://ingersollwellness.janeapp.com/locations/ingersoll-wellness-hub"
OFFICE_ADDRESS = "163 Thames Street South, Ingersoll, ON N5C 3L8, Canada"
# Ingersoll municipal centre from published place coordinates, used only to
# establish broad separation. This is NOT represented as a business coordinate.
TOWN_REFERENCE = (43.03917, -80.88361)
REGION_REFERENCE = (42.717491, -81.57066)

def _distance_km(a, b):
    rad = math.pi/180
    delta = (math.sin((a[0]-b[0])*rad/2)**2 +
             math.cos(a[0]*rad)*math.cos(b[0]*rad) *
             math.sin((a[1]-b[1])*rad/2)**2)
    return 12742*math.asin(min(1, math.sqrt(delta)))

def adjudicate_n0l(doc):
    if doc.get('fsa')!='N0L':
        return doc
    if _distance_km(REGION_REFERENCE,TOWN_REFERENCE) <= 50:
        raise RuntimeError('Geographic separation between Ingersoll and N0L unproven')
    required={
        'map_movement_v7_checkbox_on|'+'|'.join(map(str,(n,e,0,q)))
        for n in (-3.4,0.0,3.4) for e in (-3.4,0.0,3.4)
        for q in ('psychotherapist','psychologist')}
    tiles=doc.get('complete_tiles',{})
    if not required <= set(tiles):
        return doc
    if doc.get('pending') or doc.get('capped_leaf_tiles'):
        return doc
    remaining=[]
    matched=0
    for key in required:
        tile=tiles[key]
        if (tile.get('status')!='observed'
                or tile.get('map_area_search_verified') is not True
                or tile.get('capped')):
            return doc
        for link in tile.get('unresolved',[]):
            if (link.get('name')==PLACE_NAME and
                    PLACE_KEY in link.get('url','')):
                matched+=1
                continue
            remaining.append(link)
    if len(remaining)!=0 or matched!=1:
        return doc
    reviewed={
        'business_name': PLACE_NAME,
        'google_place_key': PLACE_KEY,
        'google_source_url': next(
            link['url'] for tile in (tiles[k] for k in required)
            for link in tile.get('unresolved', [])
            if PLACE_KEY in link.get('url','')),
        'primary_practitioner_url': PRIMARY_SOURCE,
        'practitioner_booking_url': BOOKING_SOURCE,
        'office_address': OFFICE_ADDRESS,
        'review_basis':'The named practitioner advertises the single Ingersoll in-office location; the N0L reference is more than 50 km away from Ingersoll municipal centre; not an inferred Google coordinate.',
        'google_place_coordinate_available': False,
        'outside_region_from_primary_office_evidence': True,
        'review_date_utc':'2026-11-23',
    }
    doc['externally_verified_exterior_links']=[reviewed]
    # Retain the original unresolved Google URL, which has no coordinates.
    # This status records the separately verified exterior business, rather
    # than pretending the place coordinate became available.
    doc['status']='verified_local_tiles_with_exterior_exception'
    return doc
