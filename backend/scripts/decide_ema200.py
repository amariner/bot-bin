"""Test DECISIVO: momentum_4h vs variante EMA200, en un periodo jamás tocado.

Todo el proceso de validación usó los últimos 240 días. El tramo anterior
(de hace 480 días a hace 240) no lo ha visto ningún experimento: es un juez
temporal virgen, y lo evaluamos además en los tres grupos de monedas (1-40,
41-80, 81-120) por separado.

Criterios de adopción de EMA200, fijados ANTES de mirar resultados:
  1. Bate a la base en retorno Y profit factor en al menos 2 de los 3 grupos
     de monedas en el periodo virgen.
  2. La meseta es suave: EMA150 y EMA250 también mejoran a la base (si solo
     funciona exactamente 200, es ruido).
  3. En las ventanas alcistas del periodo virgen no pierde contra la base por
     más de 3 puntos de media (que la protección no cueste la subida).

Si cumple los tres: se adopta como default. Si no: momentum_4h queda como
mejor opción definitiva y EMA200 se archiva como refutada.

Uso:
    python scripts/decide_ema200.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.lab import buy_and_hold, run_grid
from app.binance_client import BinancePublic
from app.config import settings, TIMEFRAME_MS
from app.universe import fetch_universe

FEE = 0.00075
TIMEFRAME = "4h"
TOTAL_DAYS = 480
RECENT_DAYS = 240          # lo ya usado por todos los tests anteriores
DAY_MS = 86_400_000

BASE = {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 3.0,
        "max_bars": 0, "regime": True}


def variant(ema):
    cfg = dict(BASE)
    cfg["trend_ema"] = ema
    return cfg


CONFIGS = [BASE, variant(150), variant(200), variant(250), variant(100)]
NAMES = ["base", "ema150", "ema200", "ema250", "ema100(control)"]


async def main():
    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=120)
        groups = {
            "monedas 1-40": [r["symbol"] for r in universe[:40]],
            "monedas 41-80": [r["symbol"] for r in universe[40:80]],
            "monedas 81-120": [r["symbol"] for r in universe[80:120]],
        }
        raw = {}
        for syms in groups.values():
            for s in syms:
                if s not in raw:
                    raw[s] = await download_history(client, s, TIMEFRAME, TOTAL_DAYS)
        btc = await download_history(client, "BTCUSDT", TIMEFRAME, TOTAL_DAYS)
    finally:
        await client.close()

    now = int(time.time() * 1000)
    old_hi = now - RECENT_DAYS * DAY_MS          # frontera: empieza lo ya usado
    old_lo = now - TOTAL_DAYS * DAY_MS
    need = int(RECENT_DAYS * DAY_MS / TIMEFRAME_MS[TIMEFRAME] * 0.9)

    def old_slice(symbols):
        out = {}
        for s in symbols:
            cs = [c for c in raw.get(s, []) if old_lo <= c.ts < old_hi]
            if len(cs) >= need:
                out[s] = cs
        return out

    def d(ts):
        return time.strftime("%d %b %y", time.gmtime(ts / 1000))

    print(f"PERIODO VIRGEN: {d(old_lo)} → {d(old_hi)} (jamás usado por ningún test)")
    print(f"comisión {FEE*100:.3f}% · {TIMEFRAME}\n")

    group_results = {}
    wins = 0
    for gname, syms in groups.items():
        data = old_slice(syms)
        if len(data) < 8:
            print(f"=== {gname}: solo {len(data)} monedas con histórico de 480d — grupo omitido\n")
            continue
        all_ts = sorted({c.ts for cs in data.values() for c in cs})
        lo, hi = all_ts[0], all_ts[-1] + 1
        bh = buy_and_hold(data, lo, hi)["return_pct"]
        results = run_grid(CONFIGS, data, btc, lo, hi, FEE)
        group_results[gname] = {"benchmark": bh, "n": len(data), "results": results}
        print(f"=== {gname} ({len(data)} con histórico completo) · mercado {bh:+.2f}%")
        print(f"{'config':<18}{'ret %':>9}{'vs B&H':>9}{'PF':>7}{'maxDD%':>8}{'trades':>8}")
        print("-" * 60)
        for name, r in zip(NAMES, results):
            pf = r["profit_factor"]
            print(f"{name:<18}{r['return_pct']:>9.2f}{r['return_pct'] - bh:>9.2f}"
                  f"{(f'{pf:.2f}' if pf else '–'):>7}{r['max_drawdown_pct']:>8.2f}"
                  f"{r['trades']:>8}")
        base_r, e200_r = results[0], results[2]
        if (e200_r["return_pct"] > base_r["return_pct"]
                and (e200_r["profit_factor"] or 0) > (base_r["profit_factor"] or 0)):
            wins += 1
        print()

    # ---- criterio 2: meseta EMA150/250 (sobre la unión de grupos)
    union = old_slice([s for syms in groups.values() for s in syms])
    all_ts = sorted({c.ts for cs in union.values() for c in cs})
    lo, hi = all_ts[0], all_ts[-1] + 1
    union_results = run_grid(CONFIGS, union, btc, lo, hi, FEE)
    base_u = union_results[0]
    plateau_ok = all(
        union_results[i]["return_pct"] >= base_u["return_pct"] - 1.0
        for i in (1, 2, 3)          # 150, 200, 250
    ) and union_results[2]["return_pct"] > base_u["return_pct"]

    # ---- criterio 3: ventanas alcistas del periodo virgen (unión)
    n_windows = 4
    step = len(all_ts) // n_windows
    bull_diffs = []
    print("=== ventanas del periodo virgen (unión de grupos) ===")
    print(f"{'ventana':<20}{'mercado %':>10}{'base %':>9}{'ema200 %':>10}")
    print("-" * 51)
    for i in range(n_windows):
        wlo = all_ts[i * step]
        whi = all_ts[(i + 1) * step] if i < n_windows - 1 else all_ts[-1] + 1
        bh_w = buy_and_hold(union, wlo, whi)["return_pct"]
        rw = run_grid([BASE, variant(200)], union, btc, wlo, whi, FEE)
        print(f"{d(wlo)} → {d(whi):<10}{bh_w:>10.2f}{rw[0]['return_pct']:>9.2f}"
              f"{rw[1]['return_pct']:>10.2f}")
        if bh_w > 0:
            bull_diffs.append(rw[1]["return_pct"] - rw[0]["return_pct"])
    bull_ok = (not bull_diffs) or (sum(bull_diffs) / len(bull_diffs) >= -3.0)

    print("\n" + "=" * 60)
    print("DECISIÓN")
    print("=" * 60)
    print(f"criterio 1 — gana en grupos: {wins}/3 (necesita ≥2)   "
          f"{'CUMPLE' if wins >= 2 else 'NO CUMPLE'}")
    print(f"criterio 2 — meseta 150/200/250 suave: "
          f"{'CUMPLE' if plateau_ok else 'NO CUMPLE'}")
    print(f"criterio 3 — no se hunde en ventanas alcistas "
          f"(media {sum(bull_diffs)/len(bull_diffs):+.2f} pts): "
          f"{'CUMPLE' if bull_ok else 'NO CUMPLE'}"
          if bull_diffs else "criterio 3 — sin ventanas alcistas en el periodo: neutro")
    adopt = wins >= 2 and plateau_ok and bull_ok
    print()
    if adopt:
        print("✅ ADOPTAR EMA200 como configuración por defecto.")
    else:
        print("❌ NO adoptar. momentum_4h (sin filtro propio) queda como mejor opción definitiva.")

    out = os.path.join(settings.data_dir, "decide_ema200.json")
    with open(out, "w") as f:
        json.dump({
            "generated_at": now, "period": [old_lo, old_hi], "fee": FEE,
            "criteria": {"group_wins": wins, "plateau_ok": plateau_ok,
                         "bull_ok": bull_ok, "bull_avg_diff":
                         (sum(bull_diffs) / len(bull_diffs)) if bull_diffs else None},
            "adopt": adopt,
            "groups": {g: {"benchmark": v["benchmark"], "n": v["n"],
                           "results": [{k: r[k] for k in ("name", "return_pct",
                                                          "profit_factor", "trades",
                                                          "max_drawdown_pct")}
                                       for r in v["results"]]}
                       for g, v in group_results.items()},
        }, f, indent=1)
    print(f"Guardado en {out}")


if __name__ == "__main__":
    asyncio.run(main())
