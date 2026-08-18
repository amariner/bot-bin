"""FASE 3 — el test final. Se ejecuta UNA vez con los finalistas de experiment.py.

Dos validaciones independientes:

  1. HOLDOUT TEMPORAL  — el último tramo del histórico, no usado para elegir.
  2. HOLDOUT DE SÍMBOLOS — los pares del puesto 41 al 80 del ranking por
     volumen, que NUNCA han intervenido en ningún ajuste. Es la prueba más
     dura: si la ventaja es real y no un artefacto de esas 33 monedas
     concretas, debe aparecer también aquí.

Y todo contra el benchmark de comprar y mantener, con dos niveles de comisión.

Uso:
    python scripts/holdout.py                     # usa data/experiment.json
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.lab import buy_and_hold, describe, run_grid, split_periods
from app.binance_client import BinancePublic
from app.config import settings, TIMEFRAME_MS
from app.universe import fetch_universe

FEE_TAKER = 0.001
FEE_BNB = 0.00075


async def load(client, symbols, timeframe, days):
    expected = days * 86_400_000 // TIMEFRAME_MS[timeframe]
    data = {}
    for sym in symbols:
        candles = await download_history(client, sym, timeframe, days)
        if len(candles) >= expected * 0.9:
            data[sym] = candles
    return data


def d(ts):
    return time.strftime("%d %b %y", time.gmtime(ts / 1000))


def show(title, results, bench, fee):
    print(f"\n{title}  ·  comisión {fee * 100:.3f}%  ·  "
          f"comprar y mantener {bench:+.2f}%")
    print(f"{'configuración':<44}{'ret %':>8}{'vs B&H':>9}{'PF':>6}"
          f"{'maxDD%':>8}{'trades':>8}{'días+%':>8}")
    print("-" * 91)
    for r in results:
        pf = r["profit_factor"]
        print(f"{r['name']:<44}{r['return_pct']:>8.2f}{r['return_pct'] - bench:>9.2f}"
              f"{(f'{pf:.2f}' if pf else '–'):>6}{r['max_drawdown_pct']:>8.2f}"
              f"{r['trades']:>8}{r['positive_days_pct']:>8.1f}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--experiment", default="experiment.json")
    ap.add_argument("--out", default="holdout.json")
    args = ap.parse_args()

    exp_path = os.path.join(settings.data_dir, args.experiment)
    if not os.path.exists(exp_path):
        print("Falta data/experiment.json. Ejecuta antes scripts/experiment.py")
        return
    with open(exp_path) as f:
        exp = json.load(f)
    finalists = exp.get("robust", [])[: args.top]
    if not finalists:
        print("experiment.json no tiene configuraciones robustas: no hay nada que testear.")
        return
    configs = [x["cfg"] for x in finalists]
    print(f"Finalistas: {[x['name'] for x in finalists]}\n")

    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=80)
        train_symbols = [r["symbol"] for r in universe[:40]]
        fresh_symbols = [r["symbol"] for r in universe[40:80]]

        data = await load(client, train_symbols, args.timeframe, args.days)
        fresh = await load(client, fresh_symbols, args.timeframe, args.days)
        btc = await download_history(client, "BTCUSDT", args.timeframe, args.days)
    finally:
        await client.close()

    train, select, holdout = split_periods(data)
    print("=" * 91)
    print(f"TEST 1 · HOLDOUT TEMPORAL   {d(holdout[0])} → {d(holdout[1])}   "
          f"({len(data)} símbolos)")
    print("=" * 91)
    bh = buy_and_hold(data, *holdout)["return_pct"]
    time_results = {}
    for fee in (FEE_TAKER, FEE_BNB):
        res = run_grid(configs, data, btc, holdout[0], holdout[1], fee)
        time_results[fee] = res
        show("resultado", res, bh, fee)

    # Periodo completo sobre símbolos nunca vistos
    all_ts = sorted({c.ts for cs in fresh.values() for c in cs})
    lo, hi = all_ts[0], all_ts[-1] + 1
    print("\n" + "=" * 91)
    print(f"TEST 2 · SÍMBOLOS NUNCA USADOS (puestos 41-80)   {d(lo)} → {d(hi)}   "
          f"({len(fresh)} símbolos)")
    print("=" * 91)
    bh_f = buy_and_hold(fresh, lo, hi)["return_pct"]
    fresh_results = {}
    for fee in (FEE_TAKER, FEE_BNB):
        res = run_grid(configs, fresh, btc, lo, hi, fee)
        fresh_results[fee] = res
        show("resultado", res, bh_f, fee)

    # ----------------------------------------------------------------- veredicto
    print("\n" + "=" * 91)
    print("VEREDICTO FINAL")
    print("=" * 91)
    # Una configuración solo aprueba si supera el benchmark en LOS DOS tests.
    # Ganar en uno y hundirse en el otro significa que la ventaja depende del
    # tramo concreto de mercado, no de la estrategia.
    def beats(r, bench):
        return (r["return_pct"] > max(0.0, bench)
                and (r["profit_factor"] or 0) > 1.0 and r["trades"] >= 20)

    time_by_name = {r["name"]: r for r in time_results[FEE_BNB]}
    winners, partial = [], []
    for r in fresh_results[FEE_BNB]:
        t = time_by_name.get(r["name"])
        ok_fresh = beats(r, bh_f)
        ok_time = t is not None and beats(t, bh)
        if ok_fresh and ok_time:
            winners.append(r)
        elif ok_fresh or ok_time:
            partial.append((r, t, ok_fresh, ok_time))

    if winners:
        best = max(winners, key=lambda r: r["profit_factor"] or 0)
        print(f"✅ {best['name']} supera el benchmark en AMBOS tests.")
        print(f"   Símbolos nuevos: {best['return_pct']:+.2f}% vs {bh_f:+.2f}% · "
              f"PF {best['profit_factor']} · {best['trades']} operaciones")
        print("   => candidata seria. Siguiente paso: paper trading prolongado.")
    elif partial:
        print("⚠️ Ninguna configuración aprueba los dos tests. Resultados partidos:")
        for r, t, ok_fresh, ok_time in partial:
            print(f"   {r['name']}")
            print(f"     símbolos nuevos: {r['return_pct']:+.2f}% vs {bh_f:+.2f}% "
                  f"({'PASA' if ok_fresh else 'FALLA'})")
            if t:
                print(f"     periodo nuevo:   {t['return_pct']:+.2f}% vs {bh:+.2f}% "
                      f"({'PASA' if ok_time else 'FALLA'})")
        print("   Ganar en un test y hundirse en el otro apunta a que la ventaja")
        print("   depende del régimen de mercado. Ejecuta scripts/diagnose.py.")
    else:
        print("❌ Ninguna finalista bate al benchmark en ningún test.")
        print("   La ventaja no generaliza: no vale para dinero real.")

    out = {
        "generated_at": int(time.time() * 1000),
        "timeframe": args.timeframe,
        "finalists": [x["name"] for x in finalists],
        "time_holdout_results": {str(k): [{kk: r[kk] for kk in
                                           ("name", "return_pct", "profit_factor",
                                            "trades", "max_drawdown_pct")}
                                          for r in v] for k, v in time_results.items()},
        "benchmark_time_holdout": bh, "benchmark_fresh_symbols": bh_f,
        "time_holdout_period": holdout, "fresh_symbols": len(fresh),
        "fresh_results": {str(k): [{kk: r[kk] for kk in
                                    ("name", "return_pct", "profit_factor", "trades",
                                     "max_drawdown_pct", "win_rate_pct", "positive_days_pct")}
                                   for r in v] for k, v in fresh_results.items()},
        "verdict": "pass" if winners else "fail",
    }
    path = os.path.join(settings.data_dir, args.out)
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nGuardado en {path}")


if __name__ == "__main__":
    asyncio.run(main())
