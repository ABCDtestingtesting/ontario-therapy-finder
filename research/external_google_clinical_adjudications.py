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
     'https://www.profilecanada.com/companydetail.cfm?company=2386071_Humber_Green_Counselling_Etobicoke_ON'),
    ('google:0x882b3a56ab7fea49:0xae7bb2effa711739',
     'Humber Green Counselling', 43.7369548, -79.6026259,
     'https://www.yellowpages.ca/bus/Ontario/Etobicoke/Humber-Green-Counselling/7540850.html'),
    ('google:0x882b3180a314fd7b:0xd701add58802c8e',
     'Empower Wellness Counseling Services', 43.757039, -79.5586757,
     'https://medimap.ca/clinic/mental-health/on/north-york/empower-wellness-counseling-services'),
    ('google:0x882b2fe3d2c1629d:0xe44d6ae6cfd2aa08',
     'Clinic For Emotional Wellness Inc', 43.7714461, -79.5442528,
     'https://the-clinic-for-emotional-wellness-inc.vaughandirect.ca/'),
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
