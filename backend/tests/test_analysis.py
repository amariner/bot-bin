"""El análisis convierte el registro en conclusiones. Si se equivoca al contar,
las decisiones sobre la estrategia se tomarían con datos falsos."""
from app.analysis import analyse


def ev(ts, type_, payload):
    return {"ts": ts, "type": type_, "payload": payload}


def trade(sym, pnl, entry_ts=0, exit_ts=3_600_000, reason="stop-loss", fees=1.0):
    return {"symbol": sym, "pnl": pnl, "entry_ts": entry_ts, "exit_ts": exit_ts,
            "exit_reason": reason, "fees": fees}


STATE = {"status": "running", "strategy": "momentum_4h", "timeframe": "4h",
         "open_positions": [], "equity": 10_000, "candles_processed": 100,
         "signals_seen": 5, "signals_rejected": 3, "regime_risk_on": True,
         "circuit_breaker": False}


def test_sin_datos_no_inventa_conclusiones():
    r = analyse([], [], [], STATE)
    assert r["operaciones"]["total"] == 0
    assert any("no hay nada que concluir" in c for c in r["conclusiones"])


def test_cuenta_motivos_de_descarte():
    events = [
        ev(1, "signal_skipped", {"symbol": "AUSDT", "reason": "sin huecos (5/5 posiciones)"}),
        ev(2, "signal_skipped", {"symbol": "BUSDT", "reason": "sin huecos (5/5 posiciones)"}),
        ev(3, "signal_skipped", {"symbol": "CUSDT", "reason": "régimen BTC bajista"}),
        ev(4, "open", {"position": {"symbol": "DUSDT"}}),
    ]
    r = analyse(events, [], [], STATE)
    assert r["motivos_de_descarte"]["sin huecos (5/5 posiciones)"] == 2
    assert r["motivos_de_descarte"]["régimen BTC bajista"] == 1
    assert r["eventos_por_tipo"]["open"] == 1
    # el cuello de botella dominante debe salir señalado como ajuste posible
    assert any("límite de 5 posiciones" in c for c in r["conclusiones"])


def test_metricas_de_operaciones():
    trades = [trade("A", 30.0), trade("B", -10.0), trade("C", 20.0), trade("D", -20.0)]
    r = analyse([], trades, [], STATE)
    o = r["operaciones"]
    assert o["total"] == 4
    assert o["ganadoras"] == 2 and o["perdedoras"] == 2
    assert o["acierto_pct"] == 50.0
    assert o["pnl_total"] == 20.0
    assert o["profit_factor"] == round(50 / 30, 2)
    assert o["mejor"]["symbol"] == "A" and o["peor"]["symbol"] == "D"


def test_profit_factor_sin_perdidas_no_divide_por_cero():
    r = analyse([], [trade("A", 10.0), trade("B", 5.0)], [], STATE)
    assert r["operaciones"]["profit_factor"] is None


def test_avisa_de_muestra_insuficiente():
    trades = [trade(f"S{i}", 1.0) for i in range(5)]
    r = analyse([], trades, [], STATE)
    assert any("muestra insuficiente" in c for c in r["conclusiones"])


def test_calcula_peor_bache_del_capital():
    equity = [{"ts": i, "equity": v} for i, v in
              enumerate([10_000, 10_500, 9_450, 9_800])]
    r = analyse([], [], equity, STATE)
    # cae de 10.500 a 9.450 => 10%
    assert r["capital"]["peor_bache_pct"] == 10.0
    assert r["capital"]["maximo"] == 10_500


def test_filtra_por_ventana_temporal():
    events = [ev(1_000, "open", {"position": {"symbol": "AUSDT"}}),
              ev(9_000, "open", {"position": {"symbol": "BUSDT"}})]
    r = analyse(events, [], [], STATE, since_ts=5_000)
    assert r["eventos_por_tipo"]["open"] == 1


def test_señala_el_peso_de_las_comisiones():
    trades = [trade("A", 10.0, fees=5.0), trade("B", 10.0, fees=5.0)]
    r = analyse([], trades, [], STATE)
    assert r["operaciones"]["comisiones"] == 10.0
    assert any("comisiones se comen" in c for c in r["conclusiones"])
