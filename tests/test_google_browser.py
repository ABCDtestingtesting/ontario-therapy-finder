from finder.google_browser import place_coordinates,name_from_url,grid_points

def test_place_data_links_coordinates():
    url='https://www.google.com/maps/place/Friendly+Therapy/data=!4m6!8m2!3d43.25123!4d-79.86423?hl=en'
    assert place_coordinates(url)==(43.25123,-79.86423)
    assert name_from_url(url)=='Friendly Therapy'

def test_place_legacy_coordinates():
    assert place_coordinates('https://www.google.com/maps/place/a/data=!2d-79.88!3d43.21')==(43.21,-79.88)

def test_map_viewport_is_not_business_location():
    assert place_coordinates('https://www.google.com/maps/place/a/@43.25,-79.8,16z') is None

def test_bounding_box_cells_are_covered():
    pts=list(grid_points((43.20,-79.90,43.23,-79.86),cell_km=1))
    assert len(pts)>5
    assert len(pts)==len(set(pts))
    assert all(43.20<=lat<=43.23 and -79.90<=lon<=-79.86 for lat,lon in pts)
