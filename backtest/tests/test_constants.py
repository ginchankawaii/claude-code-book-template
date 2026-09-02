from erb.constants import LONG_ONLY, is_excluded, normalize_code


def test_excluded_codes_match_four_and_five_digit():
    for code in ("8053", "80530", "9719", "97190", "7518", "75180"):
        assert is_excluded(code), code


def test_non_excluded_codes_pass():
    for code in ("8697", "86970", "7517", "80531"):
        assert not is_excluded(code), code


def test_normalize_code_strips_float_artifact():
    assert normalize_code(86970.0) == "86970"
    assert normalize_code(" 8697 ") == "8697"


def test_long_only_is_hardcoded():
    assert LONG_ONLY is True
