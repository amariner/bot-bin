"""Banco de experimentos: partición en 3 periodos, benchmark y ejecución paralela.

Metodología (para no autoengañarse):
  TRAIN   — se explora la rejilla completa aquí.
  SELECT  — se comprueba cuáles de las buenas en TRAIN siguen siéndolo aquí.
            Sirve para descartar sobreajuste sin tocar el periodo final.
  HOLDOUT — se usa UNA sola vez, al final, con los 2-3 finalistas. Es el
            veredicto. Si se usa para elegir, deja de ser un test honesto.

Además, todo resultado se compara contra comprar y mantener el universo
(equiponderado): una estrategia que gana menos que no hacer nada no aporta.
"""
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Optional, Tuple

from ..config import settings
from ..models import Candle
from ..regime import MarketRegime
from ..strategy.meanrev import MeanReversionRSI
from ..strategy.momentum import MomentumBreakout
from .runner import run_backtest

# Los procesos hijos comparten estos datos vía variable global (se heredan por fork)
_DATA: Dict[str, List[Candle]] = {}
_BTC: List[Candle] = []


def init_worker(data: Dict[str, List[Candle]], btc: List[Candle]):
    global _DATA, _BTC
    _DATA = data
    _BTC = btc


def build_strategy(cfg: dict):
    kind = cfg.get("strategy", "momentum")
    if kind == "meanrev":
        return MeanReversionRSI(
            oversold=cfg.get("oversold", 28.0),
            trend_ema=cfg.get("trend_ema", 200),
            atr_stop=cfg.get("atr_stop", 2.0),
            atr_tp=cfg.get("atr_tp", 2.0),
        )
    return MomentumBreakout(
        lookback=cfg.get("lookback", 20),
        vol_mult=cfg.get("vol_mult", 2.5),
        atr_stop=cfg.get("atr_stop", 2.0),
        atr_tp=cfg.get("atr_tp", 3.0),
        max_bars=cfg.get("max_bars", 48),
        trail_atr=cfg.get("trail_atr", 0.0),
        trend_ema=cfg.get("trend_ema", 0),
        min_atr_pct=cfg.get("min_atr_pct", 0.0),
        max_atr_pct=cfg.get("max_atr_pct", 0.0),
        min_breakout=cfg.get("min_breakout", 0.0),
        exit_ema=cfg.get("exit_ema", 0),
    )


def describe(cfg: dict) -> str:
    if cfg.get("strategy") == "meanrev":
        return (f"meanrev os{cfg.get('oversold', 28)} ema{cfg.get('trend_ema', 200)}"
                + (" +BTC" if cfg.get("regime") else ""))
    bits = [f"lb{cfg.get('lookback', 20)}", f"v{cfg.get('vol_mult', 2.5)}",
            f"sl{cfg.get('atr_stop', 2.0)}"]
    if cfg.get("exit_ema"):
        bits.append(f"outEMA{cfg['exit_ema']}")
    elif cfg.get("trail_atr"):
        bits.append(f"trail{cfg['trail_atr']}")
    else:
        bits.append(f"tp{cfg.get('atr_tp', 3.0)}")
    if cfg.get("trend_ema"):
        bits.append(f"ema{cfg['trend_ema']}")
    if cfg.get("min_atr_pct"):
        bits.append(f"atr>{cfg['min_atr_pct'] * 100:.1f}%")
    if cfg.get("max_atr_pct"):
        bits.append(f"atr<{cfg['max_atr_pct'] * 100:.0f}%")
    if cfg.get("min_breakout"):
        bits.append(f"brk{cfg['min_breakout'] * 100:.1f}%")
    if cfg.get("max_bars") and cfg.get("max_bars") != 48:
        bits.append(f"t{cfg['max_bars']}")
    if cfg.get("regime"):
        bits.append("+BTC")
    return " ".join(bits)


def _slice(data: Dict[str, List[Candle]], lo: int, hi: int) -> Dict[str, List[Candle]]:
    return {s: [c for c in cs if lo <= c.ts < hi] for s, cs in data.items()}


def run_one(job: Tuple[dict, int, int, float]) -> dict:
    """Ejecuta una configuración en un tramo temporal. Pensado para el pool."""
    cfg, lo, hi, fee = job
    data = _slice(_DATA, lo, hi)
    regime = None
    if cfg.get("regime"):
        regime = MarketRegime([c for c in _BTC if c.ts < hi], ema_period=50)
    r = run_backtest(build_strategy(cfg), data, capital=settings.initial_capital,
                     regime=regime, fee_rate=fee, keep_details=False)
    r["name"] = describe(cfg)
    r["cfg"] = cfg
    return r


def run_grid(configs: List[dict], data: Dict[str, List[Candle]], btc: List[Candle],
             lo: int, hi: int, fee: float, workers: Optional[int] = None) -> List[dict]:
    workers = workers or max(1, (os.cpu_count() or 4) - 2)
    jobs = [(cfg, lo, hi, fee) for cfg in configs]
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker,
                             initargs=(data, btc)) as pool:
        return list(pool.map(run_one, jobs, chunksize=1))


def buy_and_hold(data: Dict[str, List[Candle]], lo: int, hi: int) -> dict:
    """Referencia: comprar todo el universo a partes iguales y no tocar nada."""
    rets = []
    for cs in data.values():
        window = [c for c in cs if lo <= c.ts < hi]
        if len(window) > 2 and window[0].close > 0:
            rets.append(window[-1].close / window[0].close - 1)
    if not rets:
        return {"return_pct": 0.0, "symbols": 0}
    avg = sum(rets) / len(rets)
    return {"return_pct": round(avg * 100, 2), "symbols": len(rets),
            "median_pct": round(sorted(rets)[len(rets) // 2] * 100, 2)}


def split_periods(data: Dict[str, List[Candle]],
                  train: float = 0.45, select: float = 0.30):
    """Devuelve (train, select, holdout) como pares (desde, hasta) en ms."""
    all_ts = sorted({c.ts for cs in data.values() for c in cs})
    n = len(all_ts)
    a = all_ts[0]
    b = all_ts[int(n * train)]
    c = all_ts[int(n * (train + select))]
    d = all_ts[-1] + 1
    return (a, b), (b, c), (c, d)
