"""Validación fuera de muestra ("test invertido") sobre datos históricos.

Idea: NO vale probar mil configuraciones y quedarse con la que mejor sale — eso
es sobreajuste y no sirve para predecir nada. Aquí partimos el histórico en dos:

  IN-SAMPLE  (periodo antiguo)  -> se busca la mejor configuración
  OUT-SAMPLE (periodo reciente) -> se verifica esa configuración en datos que
                                   NUNCA se usaron para elegirla

Si la configuración gana en in-sample y también en out-sample, hay indicio de
ventaja real. Si gana solo en in-sample, era casualidad/sobreajuste.

Uso:
    python scripts/walkforward.py --symbols 40 --days 240 --timeframe 1h
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.runner import run_backtest
from app.binance_client import BinancePublic
from app.config import settings, TIMEFRAME_MS
from app.regime import MarketRegime
from app.strategy.momentum import MomentumBreakout
from app.strategy.meanrev import MeanReversionRSI
from app.universe import fetch_universe

# Rejilla de configuraciones a explorar en in-sample
GRID = []
for lookback in (20, 40):
    for atr_stop in (1.5, 2.0):
        for atr_tp in (2.0, 3.0, 4.0):
            for vol_mult in (1.5, 2.5):
                GRID.append({
                    "strategy": "momentum", "lookback": lookback, "atr_stop": atr_stop,
                    "atr_tp": atr_tp, "vol_mult": vol_mult,
                })
GRID.append({"strategy": "meanrev"})


def build_strategy(cfg: dict):
    if cfg["strategy"] == "meanrev":
        return MeanReversionRSI()
    return MomentumBreakout(lookback=cfg["lookback"], atr_stop=cfg["atr_stop"],
                            atr_tp=cfg["atr_tp"], vol_mult=cfg["vol_mult"],
                            max_bars=cfg.get("max_bars", 48))


def label(cfg: dict, regime: bool) -> str:
    if cfg["strategy"] == "meanrev":
        base = "meanrev"
    else:
        base = (f"mom lb{cfg['lookback']} sl{cfg['atr_stop']} tp{cfg['atr_tp']} "
                f"v{cfg['vol_mult']}")
    return base + (" +BTC" if regime else "")


def split_data(data, cut_ts):
    a = {s: [c for c in cs if c.ts < cut_ts] for s, cs in data.items()}
    b = {s: [c for c in cs if c.ts >= cut_ts] for s, cs in data.items()}
    return a, b


def evaluate(cfg, use_regime, data, btc_candles, cut_ts=None, fee_rate=None):
    strat = build_strategy(cfg)
    regime = None
    if use_regime:
        candles = btc_candles if cut_ts is None else [c for c in btc_candles]
        regime = MarketRegime(candles, ema_period=50)
    return run_backtest(strat, data, capital=settings.initial_capital,
                        regime=regime, fee_rate=fee_rate, keep_details=False)


def fmt_row(name, r):
    pf = r["profit_factor"]
    return (f"{name:<32}{r['return_pct']:>9.2f}{r['max_drawdown_pct']:>9.2f}"
            f"{r['trades']:>8}{r['win_rate_pct']:>8.1f}"
            f"{(f'{pf:.2f}' if pf else '–'):>7}{r['positive_days_pct']:>9.1f}")


HEADER = (f"{'configuración':<32}{'ret %':>9}{'maxDD %':>9}{'trades':>8}"
          f"{'win %':>8}{'PF':>7}{'días+ %':>9}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--split", type=float, default=0.6, help="fracción in-sample")
    ap.add_argument("--top", type=int, default=4, help="configuraciones a validar")
    args = ap.parse_args()

    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=args.symbols)
        symbols = [r["symbol"] for r in universe]
        print(f"Descargando {args.days} días ({args.timeframe}) de {len(symbols)} símbolos…")

        data = {}
        expected = args.days * 86_400_000 // TIMEFRAME_MS[args.timeframe]
        for sym in symbols:
            candles = await download_history(client, sym, args.timeframe, args.days)
            # Descartamos símbolos jóvenes: sesgarían el test (solo monedas que
            # existen desde el principio del periodo son comparables)
            if len(candles) >= expected * 0.9:
                data[sym] = candles
        print(f"Símbolos con histórico completo: {len(data)}/{len(symbols)}")

        btc = await download_history(client, "BTCUSDT", args.timeframe, args.days)

        all_ts = sorted({c.ts for cs in data.values() for c in cs})
        cut_ts = all_ts[int(len(all_ts) * args.split)]
        in_data, out_data = split_data(data, cut_ts)
        btc_in = [c for c in btc if c.ts < cut_ts]

        def d(ts):
            return time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))

        print(f"\nIN-SAMPLE : {d(all_ts[0])} → {d(cut_ts)}  (elegimos configuración aquí)")
        print(f"OUT-SAMPLE: {d(cut_ts)} → {d(all_ts[-1])}  (validamos aquí, datos no vistos)\n")

        # ---------------------------------------------------------- in-sample
        print("=" * 82)
        print("FASE 1 — IN-SAMPLE (búsqueda)")
        print("=" * 82)
        print(HEADER)
        print("-" * 82)
        results = []
        for cfg in GRID:
            for use_regime in (False, True):
                r = evaluate(cfg, use_regime, in_data, btc_in)
                name = label(cfg, use_regime)
                results.append({"cfg": cfg, "regime": use_regime, "name": name, "in": r})
                print(fmt_row(name, r))

        # Criterio: exigimos actividad mínima y ordenamos por profit factor.
        # Sin un mínimo de operaciones, un PF alto es ruido estadístico.
        min_trades = 30
        eligible = [x for x in results
                    if x["in"]["trades"] >= min_trades and x["in"]["profit_factor"]]
        eligible.sort(key=lambda x: (x["in"]["profit_factor"], x["in"]["return_pct"]),
                      reverse=True)
        if not eligible:
            print(f"\nNinguna configuración alcanzó {min_trades} operaciones en in-sample.")
            return
        finalists = eligible[: args.top]

        # --------------------------------------------------------- out-sample
        print("\n" + "=" * 82)
        print("FASE 2 — OUT-OF-SAMPLE (validación en datos nunca usados para elegir)")
        print("=" * 82)
        print(f"{'configuración':<32}{'IS ret%':>9}{'IS PF':>8}{'OOS ret%':>10}"
              f"{'OOS PF':>8}{'OOS DD%':>9}{'OOS trd':>8}")
        print("-" * 82)
        report = []
        for x in finalists:
            oos = evaluate(x["cfg"], x["regime"], out_data, btc)
            x["out"] = oos
            report.append(x)
            pf_in = x["in"]["profit_factor"]
            pf_out = oos["profit_factor"]
            print(f"{x['name']:<32}{x['in']['return_pct']:>9.2f}{pf_in:>8.2f}"
                  f"{oos['return_pct']:>10.2f}"
                  f"{(f'{pf_out:.2f}' if pf_out else '–'):>8}"
                  f"{oos['max_drawdown_pct']:>9.2f}{oos['trades']:>8}")

        # ---------------------------------------------------------- veredicto
        print("\n" + "=" * 82)
        print("VEREDICTO")
        print("=" * 82)
        survivors = [x for x in report
                     if x["out"]["profit_factor"] and x["out"]["profit_factor"] > 1.0
                     and x["out"]["return_pct"] > 0 and x["out"]["trades"] >= 15]
        if survivors:
            best = max(survivors, key=lambda x: x["out"]["profit_factor"])
            print(f"✅ {len(survivors)}/{len(report)} configuraciones siguen siendo rentables")
            print(f"   fuera de muestra. Mejor: {best['name']}")
            print(f"   OOS: {best['out']['return_pct']:+.2f}% | PF {best['out']['profit_factor']} "
                  f"| maxDD {best['out']['max_drawdown_pct']}% | {best['out']['trades']} trades")
            print("   => indicio de ventaja real; siguiente paso: paper trading.")
        else:
            print("❌ NINGUNA configuración ganadora en in-sample sobrevive fuera de muestra.")
            print("   Traducción: lo que funcionaba era casualidad/sobreajuste, no ventaja.")
            print("   NO pasar a dinero real con estas estrategias.")

        # Curva de equity de la mejor, para pintarla en la UI
        best_cfg = (survivors[0] if survivors else report[0])
        detailed = run_backtest(build_strategy(best_cfg["cfg"]), out_data,
                                capital=settings.initial_capital,
                                regime=MarketRegime(btc, 50) if best_cfg["regime"] else None)
        out_path = os.path.join(settings.data_dir, "walkforward.json")
        with open(out_path, "w") as f:
            json.dump({
                "generated_at": int(time.time() * 1000),
                "timeframe": args.timeframe,
                "days": args.days,
                "symbols": len(data),
                "split_ts": cut_ts,
                "in_sample_range": [all_ts[0], cut_ts],
                "out_sample_range": [cut_ts, all_ts[-1]],
                "survivors": len(survivors),
                "candidates": [{
                    "name": x["name"],
                    "in_sample": {k: v for k, v in x["in"].items()
                                  if k not in ("equity_curve", "trade_list")},
                    "out_sample": {k: v for k, v in x["out"].items()
                                   if k not in ("equity_curve", "trade_list")},
                } for x in report],
                "best": {
                    "name": best_cfg["name"],
                    "config": best_cfg["cfg"],
                    "regime_filter": best_cfg["regime"],
                    "out_sample_equity_curve": detailed["equity_curve"],
                    "out_sample_metrics": {k: v for k, v in detailed.items()
                                           if k not in ("equity_curve", "trade_list")},
                    "out_sample_trades": detailed["trade_list"][:200],
                },
            }, f, indent=1)
        print(f"\nResultados guardados en {out_path}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
