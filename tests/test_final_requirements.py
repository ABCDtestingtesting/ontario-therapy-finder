"""Final candidate spacing and auditability contract."""
import pytest
from finder import rank
from finder.common import InvalidEvidence


def entry(fsa, lat, lon, status='screened'):
    return {'fsa':fsa,'latitude':lat,'longitude':lon,'status':status}


def test_selected_fsa_centres_must_be_ten_km_apart():
    # 0.075 degrees of latitude corresponds to approximately 8.34 km.
    centres={'L7A':(43.0,-80.0),'N1T':(43.075,-80.0),'L1A':(43.4,-80.0)}
    sites=[entry('L7A',43.0,-80.0),entry('N1T',43.075,-80.0),entry('L1A',43.4,-80.0)]
    assert [p['fsa'] for p in rank.pick_distinct_candidates(sites,centres)]==['L7A','L1A']


def test_ten_km_between_actual_candidate_points_too():
    centres={'L7A':(43.0,-80.0),'N1T':(43.3,-80.0),'L1A':(43.5,-80.0)}
    sites=[entry('L7A',43.1,-80.0),entry('N1T',43.11,-80.0),entry('L1A',43.5,-80.0)]
    assert [p['fsa'] for p in rank.pick_distinct_candidates(sites,centres)]==['L7A','L1A']


def test_unreviewed_housing_is_never_selected():
    centres={'L7A':(43.0,-80.0),'L1A':(43.5,-80.0)}
    sites=[entry('L7A',43,-80,'housing_photo_gap'),entry('L1A',43.5,-80)]
    assert [p['fsa'] for p in rank.pick_distinct_candidates(sites,centres)]==['L1A']


def test_hamilton_municipality_and_shared_postal_areas_excluded():
    from finder import census
    for fsa in ('L8S','L8G','L8B','L9H','L9K','L0R'):
        assert fsa in census.HAMILTON_POSTAL_AREAS
    assert 'L7A' not in census.HAMILTON_POSTAL_AREAS


def test_ranking_hamilton_fsa_fails_before_data_collection():
    with pytest.raises(InvalidEvidence,match='Hamilton municipality'):
        rank.analyse(['L9H','N1T'])
