from app.adaptive import AdaptiveConfig, AdaptiveController


def C():
    return AdaptiveController(AdaptiveConfig(base_risk=0.01, min_risk=0.0025))


def test_healthy_results_keep_base_risk():
    eq = [100, 101, 102, 103, 104]            # straight up, no drawdown
    r, reason, m = C().evaluate(eq, [10, 20, 5, 8])
    assert r == 0.01 and "healthy" in reason and m["drawdown"] == 0.0


def test_drawdown_brakes_risk_down():
    eq = [100, 120, 108, 96]                   # peak 120 -> 96 = 20% dd
    r, reason, m = C().evaluate(eq, [5, -3])
    assert r < 0.01 and m["drawdown"] >= 0.20
    assert r >= 0.0025                          # respects floor


def test_loss_streak_brakes_risk_down():
    eq = [100, 100, 100]                        # no drawdown
    r, reason, m = C().evaluate(eq, [5, -1, -1, -1, -1])  # 4-loss streak
    assert m["loss_streak"] == 4 and r < 0.01


def test_risk_recovers_to_base_after_recovery():
    eq = [100, 90, 95, 102]                     # made a new high -> dd 0
    r, _, m = C().evaluate(eq, [-2, 3, 5, 4])   # ends on wins, no streak
    assert m["drawdown"] == 0.0 and r == 0.01


def test_floor_is_respected_in_severe_case():
    eq = [100, 200, 100]                        # 50% drawdown
    r, _, _ = C().evaluate(eq, [-1]*8)          # long loss streak too
    assert r == 0.0025


def test_changed_threshold():
    c = C()
    assert c.changed(0.01, 0.008) is True       # 20% move
    assert c.changed(0.01, 0.0098) is False      # 2% move
