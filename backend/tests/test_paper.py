from app.engine.paper import PaperBroker


def test_buy_applies_slippage_and_fee():
    b = PaperBroker(fee_rate=0.001, slippage_bps=10)
    fill = b.buy(notional=1000.0, market_price=100.0)
    assert abs(fill.price - 100.1) < 1e-9          # +10 bps
    assert abs(fill.qty - 1000.0 / 100.1) < 1e-9
    assert abs(fill.fee - 1.0) < 1e-9              # 0.1% del nocional


def test_sell_applies_slippage_and_fee():
    b = PaperBroker(fee_rate=0.001, slippage_bps=10)
    fill = b.sell(qty=5.0, market_price=100.0)
    assert abs(fill.price - 99.9) < 1e-9           # -10 bps
    assert abs(fill.notional - 499.5) < 1e-9
    assert abs(fill.fee - 0.4995) < 1e-9


def test_round_trip_costs_money():
    """Comprar y vender al mismo precio debe perder comisiones + slippage."""
    b = PaperBroker(fee_rate=0.001, slippage_bps=5)
    buy = b.buy(notional=1000.0, market_price=100.0)
    sell = b.sell(qty=buy.qty, market_price=100.0)
    net = sell.notional - sell.fee - (buy.notional + buy.fee)
    assert net < 0
    assert net > -1000 * 0.004  # coste total razonable (<0.4%)
