from app.ai_stock_trader import StockDecision, _parse, size_shares


def test_parse_portfolio():
    d = _parse('前置き ```json {"note":"日銀据え置きで内需株に追い風",'
               '"decisions":[{"symbol":"7203","action":"buy","conviction":0.6,'
               '"reason":"今期営業益が予想比+15%上振れ","factors":["営業益+15%","受注好調"],'
               '"plan":"次決算まで保有、1900割れで撤退"},'
               '{"symbol":"6758","action":"skip","conviction":0.0,"reason":"決算直前"}] } ``` 終')
    assert d.ok and len(d.calls) == 2 and "日銀" in d.note
    assert d.calls[0].symbol == "7203" and d.calls[0].action == "buy"
    assert d.calls[0].conviction == 0.6 and "営業益+15%" in d.calls[0].factors
    assert d.calls[1].action == "skip"


def test_parse_invalid_is_empty():
    assert _parse("no json").ok is False
    assert _parse("no json").calls == []


def test_parse_bad_action_becomes_skip():
    d = _parse('{"decisions":[{"symbol":"1234","action":"short","conviction":0.9}]}')
    assert d.calls[0].action == "skip"


def test_size_scales_and_rounds_to_unit():
    # 3M * 5% * 0.5 = 75,000 risk; /(2000*0.08=160)=468.75 -> 400 (unit 100)
    assert size_shares(0.5, 3_000_000, 2000, 100, 0.05) == 400
    assert size_shares(0.25, 3_000_000, 2000, 100, 0.05) == 200
    assert size_shares(0.0, 3_000_000, 2000, 100, 0.05) == 0


def test_size_caps_by_margin_and_name_notional():
    # margin remaining 500k -> max 250 shares -> 200 (unit)
    assert size_shares(0.5, 3_000_000, 2000, 100, 0.05, margin_remaining=500_000) == 200
    # per-name notional 300k -> 150 -> 100 (unit)
    assert size_shares(0.5, 3_000_000, 2000, 100, 0.05, max_name_notional=300_000) == 100


def test_size_brake_reduces():
    base = size_shares(1.0, 3_000_000, 2000, 100, 0.05)
    braked = size_shares(1.0, 3_000_000, 2000, 100, 0.05, brake=0.5)
    assert 0 < braked < base
