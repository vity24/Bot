from helpers.normalize_stats import normalize_stats_input


def test_field_player():
    assert normalize_stats_input("88", "F") == "Очки 88"


def test_goalkeeper():
    assert normalize_stats_input("33 2.22", "G") == "Поб 33 КН 2.22"


def test_goalkeeper_comma():
    assert normalize_stats_input("33 2,22", "G") == "Поб 33 КН 2,22"
