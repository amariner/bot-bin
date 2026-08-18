"""Búsqueda sistemática de la mejor configuración, en 3 fases.

    FASE 1 TRAIN   — rejilla completa; nos quedamos con las que superan el
                     benchmark y tienen actividad suficiente.
    FASE 2 SELECT  — las supervivientes se prueban en un periodo distinto.
                     Solo pasan las que ganan en AMBOS (robustez, no suerte).
    FASE 3 HOLDOUT — los 3 finalistas, una sola vez, en datos vírgenes.

Uso:
    python scripts/experiment.py --symbols 40 --days 240 --timeframe 1h
    python scripts/experiment.py --stage holdout      # solo la fase final
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.lab import (buy_and_hold, describe, run_grid, split_periods)
from app.binance_client import BinancePublic
from app.config import settings, TIMEFRAME_MS
from app.universe import fetch_universe

FEE_TAKER = 0.001      # peor caso: comisión estándar sin descuentos
FEE_BNB = 0.00075      # caso realista alcanzable hoy mismo con BNB


def build_grid_exits() -> list:
    """Rejilla 2 — ataca el fallo diagnosticado: el bot se queda rezagado en los
    mercados alcistas porque el stop dinámico salta con los retrocesos normales.
    Prueba salidas que aguanten la tendencia (EMA) y trailings más anchos."""
    grid = []
    for exit_ema in (20, 50, 100):
        for vol_mult in (2.5, 4.0):
            for atr_stop in (2.0, 3.0):
                for trend_ema in (0, 100):
                    grid.append({"lookback": 20, "vol_mult": vol_mult,
                                 "atr_stop": atr_stop, "exit_ema": exit_ema,
                                 "trend_ema": trend_ema, "max_bars": 0,
                                 "regime": True})
    for trail in (5.0, 6.0, 8.0):
        for vol_mult in (2.5, 4.0):
            grid.append({"lookback": 20, "vol_mult": vol_mult, "atr_stop": 2.0,
                         "trail_atr": trail, "trend_ema": 100, "max_bars": 0,
                         "regime": True})
    # Control: la ganadora de la rejilla 1, para comparar en igualdad
    grid.append({"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0,
                 "trail_atr": 3.0, "trend_ema": 100, "max_bars": 0, "regime": True})
    return grid


def build_grid() -> list:
    """Rejilla centrada en la hipótesis: operar MENOS y dejar correr al ganador."""
    grid = []

    # A) Selectividad creciente sobre la configuración base conocida
    for vol_mult in (2.5, 4.0, 6.0):
        for lookback in (20, 40):
            for atr_tp in (3.0, 4.0):
                grid.append({"lookback": lookback, "vol_mult": vol_mult,
                             "atr_stop": 2.0, "atr_tp": atr_tp, "regime": True})

    # B) Trailing stop (dejar correr) frente a take-profit fijo
    for trail in (2.0, 3.0, 4.0):
        for vol_mult in (2.5, 4.0, 6.0):
            for lookback in (20, 40):
                grid.append({"lookback": lookback, "vol_mult": vol_mult,
                             "atr_stop": 2.0, "trail_atr": trail,
                             "max_bars": 0, "regime": True})

    # C) Filtro de tendencia del propio símbolo
    for trend_ema in (50, 100):
        for vol_mult in (2.5, 4.0):
            for trail in (0.0, 3.0):
                cfg = {"lookback": 20, "vol_mult": vol_mult, "atr_stop": 2.0,
                       "trend_ema": trend_ema, "regime": True}
                if trail:
                    cfg.update({"trail_atr": trail, "max_bars": 0})
                grid.append(cfg)

    # D) Filtros de volatilidad: evitar mercados muertos y pumps locos
    for min_atr in (0.005, 0.01):
        for max_atr in (0.0, 0.06):
            grid.append({"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0,
                         "trail_atr": 3.0, "max_bars": 0, "min_atr_pct": min_atr,
                         "max_atr_pct": max_atr, "regime": True})

    # E) Margen mínimo de rotura (evitar roturas de milímetros)
    for brk in (0.002, 0.005):
        for vol_mult in (2.5, 4.0):
            grid.append({"lookback": 20, "vol_mult": vol_mult, "atr_stop": 2.0,
                         "trail_atr": 3.0, "max_bars": 0, "min_breakout": brk,
                         "regime": True})

    # F) Stop más ancho (menos barridos) con trailing
    for atr_stop in (2.5, 3.0):
        grid.append({"lookback": 20, "vol_mult": 4.0, "atr_stop": atr_stop,
                     "trail_atr": 3.0, "max_bars": 0, "regime": True})

    # G) Controles: sin filtro de régimen y mean reversion
    grid.append({"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0,
                 "trail_atr": 3.0, "max_bars": 0, "regime": False})
    grid.append({"strategy": "meanrev", "regime": True})

    # Deduplicar
    seen, out = set(), []
    for cfg in grid:
        key = json.dumps(cfg, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(cfg)
    return out


async def load_data(args):
    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=args.symbols)
        expected = args.days * 86_400_000 // TIMEFRAME_MS[args.timeframe]
        data = {}
        for r in universe:
            candles = await download_history(client, r["symbol"], args.timeframe, args.days)
            if len(candles) >= expected * 0.9:      # solo símbolos con histórico completo
                data[r["symbol"]] = candles
        btc = await download_history(client, "BTCUSDT", args.timeframe, args.days)
        return data, btc
    finally:
        await client.close()


HDR = (f"{'configuración':<44}{'ret %':>8}{'vs B&H':>9}{'PF':>6}{'maxDD%':>8}"
       f"{'trades':>8}{'días+%':>8}")


def row(r, bench):
    pf = r["profit_factor"]
    return (f"{r['name']:<44}{r['return_pct']:>8.2f}"
            f"{r['return_pct'] - bench:>9.2f}{(f'{pf:.2f}' if pf else '–'):>6}"
            f"{r['max_drawdown_pct']:>8.2f}{r['trades']:>8}{r['positive_days_pct']:>8.1f}")


def d(ts):
    return time.strftime("%d %b %y", time.gmtime(ts / 1000))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--fee", type=float, default=FEE_TAKER)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--grid", default="entries", choices=("entries", "exits"),
                    help="entries = rejilla de selectividad; exits = rejilla de salidas")
    ap.add_argument("--out", default="experiment.json")
    args = ap.parse_args()

    data, btc = await load_data(args)
    train, select, holdout = split_periods(data)
    grid = build_grid_exits() if args.grid == "exits" else build_grid()

    print(f"{len(data)} símbolos · {args.timeframe} · {args.days} días · "
          f"comisión {args.fee * 100:.3f}% · {len(grid)} configuraciones")
    print(f"TRAIN   {d(train[0])} → {d(train[1])}")
    print(f"SELECT  {d(select[0])} → {d(select[1])}")
    print(f"HOLDOUT {d(holdout[0])} → {d(holdout[1])}  (intacto hasta la fase 3)\n")

    # ------------------------------------------------------------------ TRAIN
    bh_train = buy_and_hold(data, *train)
    print("=" * 90)
    print(f"FASE 1 · TRAIN — comprar y mantener daría {bh_train['return_pct']:+.2f}%")
    print("=" * 90)
    t0 = time.time()
    res_train = run_grid(grid, data, btc, train[0], train[1], args.fee)
    res_train.sort(key=lambda r: r["return_pct"], reverse=True)
    print(HDR)
    print("-" * 90)
    for r in res_train[:20]:
        print(row(r, bh_train["return_pct"]))
    print(f"… {len(res_train)} configuraciones en {time.time() - t0:.0f}s")

    # Criterio de paso: batir al benchmark, ser rentable y tener actividad real
    passed = [r for r in res_train
              if r["return_pct"] > max(0.0, bh_train["return_pct"])
              and r["trades"] >= 25 and (r["profit_factor"] or 0) > 1.0]
    print(f"\nSuperan TRAIN (baten B&H, PF>1, ≥25 trades): {len(passed)}")
    if not passed:
        print("Ninguna configuración supera la fase 1. No hay candidata que validar.")
        return

    # ----------------------------------------------------------------- SELECT
    bh_sel = buy_and_hold(data, *select)
    print("\n" + "=" * 90)
    print(f"FASE 2 · SELECT — comprar y mantener daría {bh_sel['return_pct']:+.2f}%")
    print("=" * 90)
    res_sel = run_grid([r["cfg"] for r in passed], data, btc, select[0], select[1], args.fee)
    by_name = {r["name"]: r for r in res_sel}
    combined = []
    for r in passed:
        s = by_name.get(r["name"])
        if s:
            combined.append({"cfg": r["cfg"], "name": r["name"], "train": r, "select": s})
    combined.sort(key=lambda x: x["select"]["return_pct"], reverse=True)
    print(f"{'configuración':<44}{'TRAIN%':>8}{'SELECT%':>9}{'SEL PF':>8}"
          f"{'SEL DD%':>9}{'SEL trd':>8}")
    print("-" * 90)
    for x in combined[:20]:
        pf = x["select"]["profit_factor"]
        print(f"{x['name']:<44}{x['train']['return_pct']:>8.2f}"
              f"{x['select']['return_pct']:>9.2f}{(f'{pf:.2f}' if pf else '–'):>8}"
              f"{x['select']['max_drawdown_pct']:>9.2f}{x['select']['trades']:>8}")

    robust = [x for x in combined
              if x["select"]["return_pct"] > max(0.0, bh_sel["return_pct"])
              and (x["select"]["profit_factor"] or 0) > 1.0
              and x["select"]["trades"] >= 15]
    print(f"\nRobustas (ganan en TRAIN y en SELECT, batiendo B&H): {len(robust)}")

    out = {
        "generated_at": int(time.time() * 1000),
        "timeframe": args.timeframe, "days": args.days, "symbols": len(data),
        "fee": args.fee,
        "periods": {"train": train, "select": select, "holdout": holdout},
        "benchmark": {"train": bh_train, "select": bh_sel},
        "train_top": [{"name": r["name"], "cfg": r["cfg"],
                       "return_pct": r["return_pct"], "profit_factor": r["profit_factor"],
                       "trades": r["trades"], "max_drawdown_pct": r["max_drawdown_pct"]}
                      for r in res_train[:25]],
        "robust": [{"name": x["name"], "cfg": x["cfg"],
                    "train": {k: x["train"][k] for k in
                              ("return_pct", "profit_factor", "trades", "max_drawdown_pct")},
                    "select": {k: x["select"][k] for k in
                               ("return_pct", "profit_factor", "trades", "max_drawdown_pct")}}
                   for x in robust],
    }
    path = os.path.join(settings.data_dir, args.out)
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"Resultados intermedios en {path}")

    if not robust:
        print("\nNinguna configuración es robusta en dos periodos distintos.")
        print("No se toca el HOLDOUT: no hay candidata que merezca el test final.")
        return
    print(f"\nFinalistas para el test final: {[x['name'] for x in robust[:args.top]]}")
    print("Ejecuta la fase 3 con: python scripts/holdout.py")


if __name__ == "__main__":
    asyncio.run(main())
