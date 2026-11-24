"""Hand-reviewed corroboration for selected, geographically observed Google places.

Each row requires exact canonical Google place ID, name and source coordinates.
Website references substantiate psychotherapy/psychological services only.
They do not establish the total number of practitioners or exhaustive coverage.
Never use a loose name, fuzzy geolocation or generalized business category.
"""
from __future__ import annotations

# (Google place ID, Google place name, latitude, longitude, independent
# clinical-service evidence URL). Official practice pages preferred.
EVIDENCE = (
    ('google:0x882b6166f4e6ab3f:0x57108e7111780b7',
     'Voice Counselling & Education Services', 43.3908075, -79.8214663,
     'https://offline.now/latest-experts/42/'),
    ('google:0x8129494982ec72c3:0xddcd2941737c360',
     'Reis Therapy Services', 43.3924894, -79.8431318,
     'https://www.ementalhealth.ca/index.php?ID=90993&m=record'),
    ('google:0x882b30d762500001:0xf976df7c92e7f871',
     'Farah Family Solutions', 43.6998414, -79.5105535,
     'https://farahfamilysolutions.com/wp-content/uploads/2024/11/PSYCHOTHERAPY-PATIENT-REFERRAL-FORM-1.pdf'),
    ('google:0x882b2fd5c6951bff:0x82040e369a9d1d5b',
     'Ridgeline Counselling', 43.7678242, -79.5198643,
     'https://medimap.ca/clinic/mental-health/on/toronto/ridgeline-counselling-services'),
    ('google:0x882b3a5401479001:0x78ff39985f674e97',
     'Humber Green Counselling', 43.7312202, -79.5999706,
     'https://www.yellowpages.ca/bus/Ontario/Etobicoke/Humber-Green-Counselling/7540850.html'),
    ('google:0x882b3a56ab7fea49:0xae7bb2effa711739',
     'Humber Green Counselling', 43.7369548, -79.6026259,
     'https://www.profilecanada.com/companydetail.cfm?company=2386071_Humber_Green_Counselling_Etobicoke_ON'),
    ('google:0x882b3180a314fd7b:0xd701add58802c8e',
     'Empower Wellness Counseling Services', 43.757039, -79.5586757,
     'https://medimap.ca/clinic/mental-health/on/north-york/empower-wellness-counseling-services'),
    ('google:0x882b2fe3d2c1629d:0xe44d6ae6cfd2aa08',
     'Clinic For Emotional Wellness Inc', 43.7714461, -79.5442528,
     'https://the-clinic-for-emotional-wellness-inc.vaughandirect.ca/'),
)

# Source positions and immutable Google place identifiers originate from the
# original geographically verified November 2026 44-shard business evidence.
# The independent URLs document actual professional mental-health service.
# A generic 'therapy' business can be MASSAGE; record nonclinical proof too.
# (original source key, exact name, lat, lon, Google Maps place ID,
#  independently corroborating URL, clinical/nonclinical)
ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS = (
    ('woolwich counselling centre:43.59398:-80.56044',
     'Woolwich Counselling Centre',43.5939832,-80.5604359,
     '0x882bee8a2b67b173:0xe09c45e7c5e4a13',
     'https://woolwichcounselling.org/services-programs/','clinical'),
    ('p.a.c.e. therapy and counselling services:42.59407:-82.38467',
     'P.A.C.E. Therapy and Counselling Services',42.5940716,-82.3846748,
     '0x88256ba3079b22dd:0x5ec103b6abdd2c62',
     'https://www.pace-inc.com/therapy','clinical'),
    ('p.a.c.e. therapy and counselling services:42.40576:-82.18621',
     'P.A.C.E. Therapy and Counselling Services',42.4057624,-82.1862095,
     '0x882ff9cba8ce150f:0xb859fb4f3279b2a7',
     'https://www.pace-inc.com/therapy','clinical'),
    ('p.a.c.e. therapy and counselling services:42.98522:-82.39902',
     'P.A.C.E. Therapy and Counselling Services',42.9852235,-82.3990197,
     '0x88259dd982c48d6d:0x773a971ba0f291ce',
     'https://www.pace-inc.com/therapy','clinical'),
    ('counselcarecanada:42.59295:-82.38618',
     'Counselcarecanada',42.5929475,-82.386185,
     '0x88255d4af9fd6b1f:0x9eba2f2b5ab10311',
     'https://www.ccclifesolutions.com/','clinical'),
    ('k. harris counselling services:43.09752:-79.09729',
     'K. Harris Counselling Services',43.0975196,-79.0972891,
     '0x89d343c8d5dab8eb:0xc05bbe885c9f0f9f',
     'https://www.kharriscounsellingservices.ca/ourteam','clinical'),
    ('nova phoenix counselling services - niagara falls:43.09219:-79.09288',
     'Nova Phoenix Counselling Services - Niagara Falls',43.0921909,-79.0928808,
     '0x89d3432e32c80809:0xd4d490120dd99d39',
     'https://novaphoenix.ca/locations/niagara-falls-therapy/','clinical'),
    ('nova phoenix counselling services - st. catharines:43.16465:-79.24308',
     'Nova Phoenix Counselling Services - St. Catharines',43.1646492,-79.2430826,
     '0x89d351726e4251ef:0x77c882181a4ed9d6',
     'https://novaphoenix.ca/therapy-offices/','clinical'),
    ('adrienne richardson niagara counselling/ online therapy:43.09739:-79.09712',
     'Adrienne Richardson Niagara Counselling/ Online Therapy',43.0973937,-79.0971165,
     '0x89d34342a0b6ec2b:0x9ab84d9e6a8316f4',
     'https://www.rainbowhealthontario.ca/service-provider-directory/adrienne-richardson-niagara-counselling-online-therapy/','clinical'),
    ('danny laramee therapy solutions:45.37361:-75.94325',
     'Danny Laramee Therapy Solutions',45.3736136,-75.9432492,
     '0x4cd1ff1c39def935:0x700b67f3d6f461c8',
     'https://dannylarameetherapy.ca/services','nonclinical'),
)

from urllib.parse import urlparse

LOOKUP = {}
for key, name, lat, lon, clinical_url in EVIDENCE:
    if key in LOOKUP or not key.startswith('google:'):
        raise RuntimeError('Duplicate/noncanonical independently reviewed Google place')
    if urlparse(clinical_url).scheme != 'https':
        raise RuntimeError('External practice source must be HTTPS')
    LOOKUP[key] = (name, lat, lon, clinical_url)


def independent_clinical_service_evidence(place):
    """Return corroborating evidence URL only for exact identified source.
    A check is about a listed clinic, never individual practitioner counts.
    """
    additional = original_google_business_corroboration(place)
    if additional and additional[0]=='clinical':
        return additional[1]
    row = LOOKUP.get(str(place.get('key') or ''))
    if row is None:
        return None
    name, lat, lon, citation = row
    if str(place.get('name') or '').casefold().strip() != name.casefold():
        return None
    url = str(place.get('source_url') or '')
    if ('google.com/maps/place/' not in url
        or place['key'].removeprefix('google:') not in url):
        return None
    try:
        if (abs(float(place['lat']) - lat) > 0.00005
            or abs(float(place['lon']) - lon) > 0.00005):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return citation

# Only an exact source key, name, Google Maps place ID, geographic coordinate
# and independent service reference can change the clinical classification.
ORIGINAL_GOOGLE_CORROBORATED = {}
for key, name, lat, lon, google_id, evidence_url, kind in ORIGINAL_GOOGLE_BUSINESS_ADJUDICATIONS:
    if key in ORIGINAL_GOOGLE_CORROBORATED or kind not in ('clinical','nonclinical'):
        raise RuntimeError('Duplicate or unclassified original Google place proof')
    if not google_id.startswith('0x') or ':0x' not in google_id:
        raise RuntimeError('Missing canonical Google business ID')
    if urlparse(evidence_url).scheme != 'https':
        raise RuntimeError('Clinical corroboration must use HTTPS')
    ORIGINAL_GOOGLE_CORROBORATED[key] = (name, lat, lon, google_id, evidence_url, kind)


def original_google_business_corroboration(place):
    row=ORIGINAL_GOOGLE_CORROBORATED.get(str(place.get('key') or ''))
    if row is None:
        return None
    name,lat,lon,google_id,evidence_url,kind=row
    if str(place.get('name','')).casefold().strip()!=name.casefold():
        return None
    url=str(place.get('source_url') or '')
    if not url.startswith('https://www.google.com/maps/place/') or ('!1s'+google_id) not in url:
        return None
    try:
        if (abs(float(place['lat'])-lat)>0.00005 or
            abs(float(place['lon'])-lon)>0.00005):
            return None
    except (TypeError,ValueError,KeyError):
        return None
    return kind,evidence_url


def independent_nonclinical_service_evidence(place):
    row=original_google_business_corroboration(place)
    return row[1] if row and row[0]=='nonclinical' else None
