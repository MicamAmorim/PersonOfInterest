from backend.app.identity_safety_patch import _face_center_inside, _parse_bbox


def test_parse_bbox_requires_positive_size():
    assert _parse_bbox('{"x": 10, "y": 20, "w": 100, "h": 200}') == (10.0, 20.0, 100.0, 200.0)
    assert _parse_bbox('{"x": 10, "y": 20, "w": 0, "h": 200}') is None
    assert _parse_bbox('not-json') is None


def test_face_center_must_be_inside_person_bbox():
    bbox = (100.0, 100.0, 200.0, 400.0)
    inside_face = [140.0, 130.0, 60.0, 60.0, 0, 0, 0, 0, 0, 0, 0.95]
    outside_face = [310.0, 130.0, 60.0, 60.0, 0, 0, 0, 0, 0, 0, 0.95]
    assert _face_center_inside(inside_face, bbox)
    assert not _face_center_inside(outside_face, bbox)
