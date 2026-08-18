"""Agregación del registro en conclusiones accionables.

La idea: no basta con guardar eventos, hay que poder responder preguntas como
"¿por qué el bot casi no compra?" o "¿las salidas están cortando ganadores?".
Este módulo convierte el log crudo en las cifras que contestan eso, y se sirve
en /api/analysis para poder consultarlo en remoto.
"""
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional

HOUR_MS = 3_600_000


def _pf(wins: float, losses: float) -> Optional[float]:
    return round(wins / losses, 2) if losses > 0 else None


def analyse(events: List[dict], trades: List[dict], equity: List[dict],
            state: dict, since_ts: int = 0) -> dict:
    """`events` y `trades` vienen de SQLite; `state` es la foto actual del bot."""
    now = int(time.time() * 1000)
    events = [e for e in events if e["ts"] >= since_ts]
    trades = [t for t in trades if t["exit_ts"] >= since_ts]
    equity = [p for p in equity if p["ts"] >= since_ts]

    by_type = Counter(e["type"] for e in events)

    # --- por qué NO compra: el dato más útil para ajustar la estrategia
    rejections = Counter()
    signals_by_symbol = defaultdict(lambda: {"señales": 0, "compradas": 0, "descartadas": 0})
    for e in events:
        p = e.get("payload") or {}
        sym = p.get("symbol") or (p.get("position") or {}).get("symbol") \
            or (p.get("trade") or {}).get("symbol")
        if e["type"] == "signal_skipped":
            rejections[p.get("reason", "desconocido")] += 1
            if sym:
                signals_by_symbol[sym]["señales"] += 1
                signals_by_symbol[sym]["descartadas"] += 1
        elif e["type"] == "open" and sym:
            signals_by_symbol[sym]["señales"] += 1
            signals_by_symbol[sym]["compradas"] += 1

    top_symbols = sorted(signals_by_symbol.items(),
                         key=lambda kv: kv[1]["señales"], reverse=True)[:10]

    # --- resultados de las operaciones cerradas
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    holds = [(t["exit_ts"] - t["entry_ts"]) / HOUR_MS for t in trades if t["exit_ts"] > t["entry_ts"]]

    trades_block = {
        "total": len(trades),
        "ganadoras": len(wins),
        "perdedoras": len(losses),
        "acierto_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "pnl_total": round(sum(t["pnl"] for t in trades), 2),
        "pnl_medio": round(sum(t["pnl"] for t in trades) / len(trades), 3) if trades else 0.0,
        "ganancia_media": round(gross_win / len(wins), 3) if wins else 0.0,
        "perdida_media": round(-gross_loss / len(losses), 3) if losses else 0.0,
        "profit_factor": _pf(gross_win, gross_loss),
        "comisiones": round(sum(t.get("fees", 0.0) for t in trades), 2),
        "horas_medias_en_cartera": round(sum(holds) / len(holds), 1) if holds else 0.0,
        "por_motivo_de_salida": dict(Counter(t["exit_reason"] for t in trades)),
        "mejor": max(trades, key=lambda t: t["pnl"], default=None),
        "peor": min(trades, key=lambda t: t["pnl"], default=None),
    }
    for k in ("mejor", "peor"):
        t = trades_block[k]
        trades_block[k] = None if not t else {
            "symbol": t["symbol"], "pnl": round(t["pnl"], 2),
            "exit_reason": t["exit_reason"],
            "horas": round((t["exit_ts"] - t["entry_ts"]) / HOUR_MS, 1),
        }

    # --- curva de capital y peor bache
    peak, max_dd = None, 0.0
    for p in equity:
        peak = p["equity"] if peak is None else max(peak, p["equity"])
        if peak > 0:
            max_dd = max(max_dd, (peak - p["equity"]) / peak)
    equity_block = {
        "muestras": len(equity),
        "inicial": round(equity[0]["equity"], 2) if equity else None,
        "actual": round(equity[-1]["equity"], 2) if equity else None,
        "maximo": round(peak, 2) if peak is not None else None,
        "peor_bache_pct": round(max_dd * 100, 2),
    }

    # --- conclusiones en texto, que es lo que se lee de un vistazo
    conclusiones = _conclusiones(by_type, rejections, trades_block, state, events)

    return {
        "generado": now,
        "desde": since_ts or (events[0]["ts"] if events else now),
        "horas_analizadas": round((now - (since_ts or (events[0]["ts"] if events else now))) / HOUR_MS, 1),
        "estado_actual": {
            "estado": state.get("status"),
            "estrategia": state.get("strategy"),
            "velas": state.get("timeframe"),
            "posiciones_abiertas": len(state.get("open_positions", [])),
            "equity": state.get("equity"),
            "revisiones": state.get("candles_processed"),
            "señales_vistas": state.get("signals_seen"),
            "señales_descartadas": state.get("signals_rejected"),
            "btc_fuerte": state.get("regime_risk_on"),
            "freno_diario": state.get("circuit_breaker"),
        },
        "eventos_por_tipo": dict(by_type),
        "motivos_de_descarte": dict(rejections.most_common()),
        "monedas_con_mas_señales": [{"symbol": s, **v} for s, v in top_symbols],
        "operaciones": trades_block,
        "capital": equity_block,
        "conclusiones": conclusiones,
    }


def _conclusiones(by_type, rejections, tr, state, events) -> List[str]:
    """Frases cortas y accionables. Solo se afirma lo que los datos sostienen."""
    out = []
    señales = by_type.get("open", 0) + by_type.get("signal_skipped", 0)
    if señales == 0 and tr["total"] == 0:
        out.append("Todavía no ha habido ninguna señal: no hay nada que concluir. "
                   "Con velas de 4h hacen falta días para acumular muestra.")
        return out

    if señales:
        ratio = by_type.get("open", 0) / señales * 100
        out.append(f"De {señales} señales detectadas, ha comprado "
                   f"{by_type.get('open', 0)} ({ratio:.0f}%).")

    if rejections:
        motivo, n = max(rejections.items(), key=lambda kv: kv[1])
        pct = n / sum(rejections.values()) * 100
        out.append(f"El motivo de descarte dominante es «{motivo}» ({n} veces, {pct:.0f}%).")
        if "sin huecos" in motivo:
            out.append("AJUSTE POSIBLE: el límite de 5 posiciones está siendo el cuello "
                       "de botella; subirlo daría más operaciones (validar antes).")
        elif "régimen BTC" in motivo:
            out.append("El filtro de Bitcoin está frenando la mayoría de señales: el bot "
                       "está en modo defensivo porque el mercado no acompaña.")
        elif "efectivo" in motivo:
            out.append("AJUSTE POSIBLE: se queda sin efectivo libre; el tamaño por "
                       "posición puede ser demasiado grande para 5 posiciones.")

    if tr["total"] == 0:
        out.append("Sin operaciones cerradas todavía: no se puede juzgar el rendimiento.")
        return out

    if tr["total"] < 20:
        out.append(f"OJO: solo {tr['total']} operaciones cerradas. Es muestra insuficiente "
                   "para sacar conclusiones fiables; hacen falta 30-50 como mínimo.")

    pf = tr["profit_factor"]
    if pf is not None:
        veredicto = "gana" if pf > 1 else "pierde"
        out.append(f"Profit factor {pf}: por cada euro perdido {veredicto} {pf}. "
                   f"Acierto {tr['acierto_pct']}%.")

    if tr["ganancia_media"] and tr["perdida_media"]:
        r = abs(tr["ganancia_media"] / tr["perdida_media"])
        out.append(f"La ganancia media ({tr['ganancia_media']}) es {r:.1f}× la pérdida "
                   f"media ({tr['perdida_media']}).")
        if r < 1.5 and tr["acierto_pct"] < 50:
            out.append("AVISO: ganancias pequeñas y acierto bajo a la vez. Si se mantiene, "
                       "es la firma de una estrategia sin ventaja.")

    salidas = tr["por_motivo_de_salida"]
    if salidas:
        principal = max(salidas.items(), key=lambda kv: kv[1])
        out.append(f"La salida más frecuente es «{principal[0]}» ({principal[1]} de "
                   f"{tr['total']}).")

    if tr["comisiones"] and tr["pnl_total"] is not None:
        bruto = tr["pnl_total"] + tr["comisiones"]
        if bruto > 0:
            peso = tr["comisiones"] / bruto * 100
            out.append(f"Las comisiones se comen el {peso:.0f}% de la ganancia bruta "
                       f"({tr['comisiones']} de {round(bruto, 2)}).")
    return out
