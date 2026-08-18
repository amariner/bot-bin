from app.engine.risk import RiskManager, DAY_MS


def mk_risk(**kw):
    defaults = dict(risk_per_trade=0.01, max_positions=5, daily_max_loss_pct=0.02,
                    max_notional_pct=0.20, min_notional=5.0)
    defaults.update(kw)
    return RiskManager(**defaults)


def test_position_sizing_risks_one_percent():
    r = mk_risk()
    # stop al 2% => nocional = equity * 1% / 2% = 50% equity, capado al 20%
    notional = r.position_notional(equity=10_000, entry=100.0, stop=98.0)
    assert notional == 2_000.0  # cap por max_notional_pct

    # stop al 10% => 10000 * 0.01 / 0.10 = 1000
    notional = r.position_notional(equity=10_000, entry=100.0, stop=90.0)
    assert abs(notional - 1_000.0) < 1e-9


def test_position_sizing_rejects_bad_inputs():
    r = mk_risk()
    assert r.position_notional(10_000, 100.0, 100.0) is None   # stop == entry
    assert r.position_notional(10_000, 100.0, 101.0) is None   # stop por encima
    assert r.position_notional(10_000, 100.0, 99.9999) is None # stop pegado
    # nocional bajo el mínimo de Binance
    assert r.position_notional(equity=20, entry=100.0, stop=50.0) is None


def test_max_positions_enforced():
    r = mk_risk()
    assert r.can_open(open_positions=4, cash=10_000, notional=100) is True
    assert r.can_open(open_positions=5, cash=10_000, notional=100) is False


def test_insufficient_cash():
    r = mk_risk()
    assert r.can_open(open_positions=0, cash=50, notional=100) is False


def test_circuit_breaker_trips_and_resets_next_day():
    r = mk_risk()
    r.roll_day(0, 10_000)
    assert r.check_circuit_breaker(9_900) is False   # -1%
    assert r.check_circuit_breaker(9_800) is True    # -2% => corta
    assert r.can_open(0, 10_000, 100) is False
    # a la misma jornada sigue cortado aunque el equity se recupere
    assert r.check_circuit_breaker(9_950) is True
    # al día siguiente se rearma
    r.roll_day(DAY_MS + 1, 9_800)
    assert r.check_circuit_breaker(9_790) is False
