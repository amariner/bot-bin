"""El bot debe aguantar patadas: reinicios, caídas y actualizaciones.

Estos tests simulan que el proceso muere en distintos momentos y comprueban
que al levantarse recuerda exactamente lo que tenía: monedas compradas, stop
dinámico ya movido, dinero libre y el freno diario.
"""
import os
import tempfile

from app.db import Database
from app.engine.core import TradingEngine
from app.engine.paper import PaperBroker
from app.engine.risk import RiskManager
from app.models import Candle
from app.strategy.momentum import MomentumBreakout
from tests.test_engine import AlwaysBuy, mk_candle


def mk_engine():
    return TradingEngine(AlwaysBuy(), capital=10_000,
                         broker=PaperBroker(fee_rate=0.001, slippage_bps=0),
                         risk=RiskManager(risk_per_trade=0.01, max_positions=5,
                                          daily_max_loss_pct=0.02,
                                          max_notional_pct=0.20, min_notional=5.0))


def test_state_roundtrip_keeps_positions_and_cash():
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    assert len(e.positions) == 1
    state = e.to_state()
    cash_before = e.cash
    pos_before = e.positions["AAAUSDT"]

    # el proceso "muere" y arranca uno nuevo
    e2 = mk_engine()
    n = e2.restore_state(state)

    assert n == 1
    assert abs(e2.cash - cash_before) < 1e-9
    p = e2.positions["AAAUSDT"]
    assert p.qty == pos_before.qty
    assert p.entry_price == pos_before.entry_price
    assert p.stop_price == pos_before.stop_price
    assert p.opened_ts == pos_before.opened_ts


def test_restore_keeps_trailing_stop_already_moved():
    """Lo más peligroso de perder: un stop que ya había subido. Si al reiniciar
    volviera al original, el bot regalaría el beneficio protegido."""
    strat = MomentumBreakout(trail_atr=3.0)
    e = TradingEngine(strat, capital=10_000,
                      broker=PaperBroker(fee_rate=0.0, slippage_bps=0),
                      risk=RiskManager())
    from app.models import Position
    pos = Position(symbol="XUSDT", qty=10.0, entry_price=100.0, stop_price=95.0,
                   take_profit=1e6, opened_ts=0, strategy="momentum", reason="t",
                   meta={"peak": 130.0})
    pos.stop_price = 118.0          # el trailing ya lo había subido
    e.positions["XUSDT"] = pos

    e2 = TradingEngine(strat, capital=10_000)
    e2.restore_state(e.to_state())
    recovered = e2.positions["XUSDT"]
    assert recovered.stop_price == 118.0
    assert recovered.meta["peak"] == 130.0


def test_restore_keeps_circuit_breaker_active():
    """Si el freno diario estaba puesto, un reinicio no puede levantarlo:
    sería una vía para saltarse el límite de pérdidas reiniciando."""
    e = mk_engine()
    e.risk.roll_day(0, 10_000)
    e.risk.check_circuit_breaker(9_700)
    assert e.risk.halted

    e2 = mk_engine()
    e2.restore_state(e.to_state())
    assert e2.risk.halted is True
    assert e2.risk.day_start_equity == 10_000
    assert e2.risk.can_open(0, 10_000, 100) is False


def test_restore_ignores_state_from_other_version():
    e = mk_engine()
    st = e.to_state()
    st["version"] = 999          # formato futuro/desconocido
    e2 = mk_engine()
    assert e2.restore_state(st) == 0
    assert e2.cash == 10_000     # arranque limpio, no estado corrupto


def test_restore_handles_empty_state():
    e = mk_engine()
    assert e.restore_state({}) == 0
    assert e.restore_state(None) == 0


def test_state_survives_a_real_sqlite_roundtrip():
    """Prueba de extremo a extremo con la base de datos de verdad, que es lo
    que hay en el volumen del servidor."""
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db = Database(path)
    e = mk_engine()
    e.on_candle_closed("BBBUSDT", [mk_candle(0, 50, 51, 49, 50)])
    db.set_kv("engine_state", e.to_state())
    db.close()

    db2 = Database(path)          # simula el contenedor nuevo montando el volumen
    e2 = mk_engine()
    n = e2.restore_state(db2.get_kv("engine_state"))
    db2.close()
    assert n == 1
    assert "BBBUSDT" in e2.positions


def test_counters_survive_restart():
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    e2 = mk_engine()
    e2.restore_state(e.to_state())
    assert e2.candles_processed == e.candles_processed
    assert e2.signals_seen == e.signals_seen


def test_restore_survives_future_schema_changes():
    """Si una actualización añade o quita campos a Position, el estado guardado
    por la versión anterior debe seguir leyéndose: al desplegar en producción no
    puede perderse una posición por un cambio de código."""
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    st = e.to_state()
    # simula un estado escrito por una versión con un campo que ya no existe
    st["positions"][0]["campo_de_una_version_vieja"] = 42

    e2 = mk_engine()
    assert e2.restore_state(st) == 1
    assert "AAAUSDT" in e2.positions


def test_restore_fills_defaults_for_new_fields():
    """Y al revés: un estado antiguo al que le falta un campo nuevo debe
    cargarse usando el valor por defecto, no fallar."""
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    st = e.to_state()
    st["positions"][0].pop("bars_held")     # campo con valor por defecto
    st["positions"][0].pop("meta")

    e2 = mk_engine()
    assert e2.restore_state(st) == 1
    assert e2.positions["AAAUSDT"].bars_held == 0
