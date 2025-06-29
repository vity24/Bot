import pytest

try:
    import handlers
except ModuleNotFoundError:
    pytest.skip("telegram not available", allow_module_level=True)


def test_parse_goalie_points_with_comma():
    points = handlers._parse_points('Поб 33 КН 2,50', 'G')
    assert int(points) == 33 * 2 + int(30 - 2.5 * 10)
