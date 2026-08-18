"""¿Adoptamos el trailing 2.0 (y/o el filtro EMA200)? Juez nuevo: monedas 81-120.

Los "vecinos" prometedores del test de sensibilidad (trailing 2.0, EMA200) se
vieron sobre las monedas 41-80, así que elegirlos mirando esos números sería
sobreajuste. Este script usa un conjunto de datos que NADIE ha tocado en todo
el proceso: los pares del puesto 81 al 120 por volumen.

Criterio de adopción (fijado ANTES de mirar los resultados):
  - El vecino debe batir a la configuración actual en retorno Y en profit factor
    sobre este conjunto nuevo, con al menos 25 operaciones.
  - Y el patrón debe ser consistente con el visto en las monedas 41-80
    (trailing más ceñido => mejor), no un salto aislado.

Uso:
    python scripts/validate_neighbors.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.lab import buy_and_hold, describe, run_grid
from app.binance_client import BinancePublic
from app.config import settings, TIMEFRAME_MS
from app.universe import fetch_universe

FEE = 0.00075
TIMEFRAME = "4h"
DAYS = 240

CONFIGS = [
    # patrón trailing: si 2.0 > 2.5 > 3.0 también aquí, el patrón es real
    {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 2.0,
     "max_bars": 0, "regime": True},
    {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 2.5,
     "max_bars": 0, "regime": True},
    {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 3.0,
     "max_bars": 0, "regime": True},               # <- configuración actual
    # el candidato EMA200 (sospechoso de ruido por el zigzag 50/100/200)
    {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 3.0,
     "trend_ema": 200, "max_bars": 0, "regime": True},
    {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 2.0,
     "trend_ema": 200, "max_bars": 0, "regime": True},
]


async def main():
    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=120)
        judge_symbols = [r["symbol"] for r in universe[80:120]]
        expected = DAYS * 86_400_000 // TIMEFRAME_MS[TIMEFRAME]
        data = {}
        for sym in judge_symbols:
            cs = await download_history(client, sym, TIMEFRAME, DAYS)
            if len(cs) >= expected * 0.9:
                data[sym] = cs
        btc = await download_history(client, "BTCUSDT", TIMEFRAME, DAYS)
    finally:
        await client.close()

    all_ts = sorted({c.ts for cs in data.values() for c in cs})
    lo, hi = all_ts[0], all_ts[-1] + 1
    bh = buy_and_hold(data, lo, hi)["return_pct"]
    print(f"JUEZ NUEVO: {len(data)} monedas (puestos 81-120), {DAYS} días, "
          f"{TIMEFRAME}, comisión {FEE*100:.3f}%")
    print(f"Comprar y mantener: {bh:+.2f}%\n")
    print(f"{'configuración':<40}{'ret %':>8}{'vs B&H':>9}{'PF':>6}"
          f"{'maxDD%':>8}{'trades':>8}")
    print("-" * 79)
    results = run_grid(CONFIGS, data, btc, lo, hi, FEE)
    for r in results:
        pf = r["profit_factor"]
        mark = "  <- actual" if r["name"] == describe(CONFIGS[2]) else ""
        print(f"{r['name']:<40}{r['return_pct']:>8.2f}{r['return_pct'] - bh:>9.2f}"
              f"{(f'{pf:.2f}' if pf else '–'):>6}{r['max_drawdown_pct']:>8.2f}"
              f"{r['trades']:>8}{mark}")

    base = results[2]
    t20 = results[0]
    t25 = results[1]
    ordered = (t20["return_pct"] >= t25["return_pct"] >= base["return_pct"])
    beats = (t20["return_pct"] > base["return_pct"]
             and (t20["profit_factor"] or 0) > (base["profit_factor"] or 0)
             and t20["trades"] >= 25)
    print("\nVEREDICTO trailing 2.0:")
    if ordered and beats:
        print("  ✅ ADOPTAR: el patrón 2.0>2.5>3.0 se repite en un conjunto virgen")
        print("     y bate a la configuración actual en retorno y PF.")
    elif beats and not ordered:
        print("  ⚠️ Gana pero el patrón no es monótono aquí: evidencia débil, no adoptar aún.")
    else:
        print("  ❌ NO adoptar: el vecino no bate a la configuración actual en datos vírgenes.")
        print("     Lo que vimos en las monedas 41-80 era ruido.")

    e200 = results[3]
    print("VEREDICTO filtro EMA200:")
    if (e200["return_pct"] > base["return_pct"]
            and (e200["profit_factor"] or 0) > (base["profit_factor"] or 0)
            and e200["trades"] >= 25):
        print("  ⚠️ Bate aquí también; aun así el zigzag EMA50/100/200 exige otro periodo antes de adoptar.")
    else:
        print("  ❌ NO adoptar: no bate a la configuración actual en datos vírgenes (ruido confirmado).")

    out = os.path.join(settings.data_dir, "validate_neighbors.json")
    with open(out, "w") as f:
        json.dump({"generated_at": int(time.time() * 1000), "benchmark": bh,
                   "symbols": len(data),
                   "results": [{k: r[k] for k in ("name", "return_pct", "profit_factor",
                                                  "trades", "max_drawdown_pct")}
                               for r in results]}, f, indent=1)
    print(f"\nGuardado en {out}")


if __name__ == "__main__":
    asyncio.run(main())
