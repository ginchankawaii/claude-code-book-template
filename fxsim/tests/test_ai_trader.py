from app.ai_trader import AIDecision, _parse, size_lots


def test_parse_valid():
    d = _parse('here is my call ```json\n{"action":"short","conviction":0.7,'
               '"reason":"weak US data","factors":["NFP miss","USD soft"]}\n``` done')
    assert d.action == "short" and abs(d.conviction - 0.7) < 1e-9
    assert "NFP miss" in d.factors


def test_parse_invalid_is_flat():
    assert _parse("no json here").action == "flat"
    assert _parse('{"action":"banana","conviction":2}').action == "flat"  # bad action -> flat


def test_parse_clamps_conviction():
    assert _parse('{"action":"long","conviction":5}').conviction == 1.0
    assert _parse('{"action":"long","conviction":-1}').conviction == 0.0


def test_size_flat_is_zero():
    assert size_lots("flat", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0) == 0.0
    assert size_lots("long", 0.0, 3_000_000, 1.0, 0.01, 0.05, 5.0) == 0.0


def test_size_scales_with_conviction():
    full = size_lots("long", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0)
    half = size_lots("long", 0.5, 3_000_000, 1.0, 0.01, 0.05, 5.0)
    assert full > 0 and abs(half - full / 2) < 0.02     # ~half the size


def test_size_respects_brake_and_cap():
    base = size_lots("long", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0)
    braked = size_lots("long", 1.0, 3_000_000, 1.0, 0.01, 0.05, 5.0, brake=0.5)
    assert braked < base
    capped = size_lots("long", 1.0, 3_000_000, 0.001, 0.01, 0.05, 0.10)  # tiny stop -> huge units
    assert capped == 0.10                                 # hard max-lots cap
