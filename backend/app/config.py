"""Configuración central del bot. Todo es sobreescribible por variable de entorno BOT_*."""
import os
from dataclasses import dataclass, field
from typing import List


def _env(name: str, default, cast=None):
    raw = os.environ.get(f"BOT_{name}")
    if raw is None:
        return default
    if cast is None:
        cast = type(default)
    if cast is bool:
        return raw.lower() in ("1", "true", "yes")
    return cast(raw)


# Bases que nunca operamos: stablecoins y activos fiat-peg (no tienen recorrido)
STABLE_BASES = {
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "EURI", "EUR", "AEUR",
    "BUSD", "PAXG", "USTC", "XUSD", "USDE", "USD1", "FDUSDT",
    "RLUSD", "BFUSD", "USDY", "PYUSD", "GUSD", "USDS",
    "XAUT",  # oro tokenizado: se mueve como el oro, no como cripto
}


@dataclass
class Settings:
    # Capital y riesgo
    initial_capital: float = _env("INITIAL_CAPITAL", 10_000.0)
    risk_per_trade: float = _env("RISK_PER_TRADE", 0.01)       # 1% del equity por operación
    max_positions: int = _env("MAX_POSITIONS", 5)
    max_position_notional_pct: float = _env("MAX_POSITION_NOTIONAL_PCT", 0.20)
    daily_max_loss_pct: float = _env("DAILY_MAX_LOSS_PCT", 0.02)  # circuit breaker -2% diario
    min_notional: float = 5.0                                   # mínimo de orden de Binance (USDT)

    # Fricción simulada (paper trading)
    fee_rate: float = _env("FEE_RATE", 0.001)                   # 0.1% por lado (taker estándar)
    slippage_bps: float = _env("SLIPPAGE_BPS", 5.0)             # 5 puntos básicos por fill

    # Universo
    universe_size: int = _env("UNIVERSE_SIZE", 100)
    quote_asset: str = "USDT"

    # Estrategia / datos
    # 4h por defecto: es el timeframe donde la ventaja resulta más estable
    # (11 configuraciones robustas frente a 2 en 1h) y donde la estrategia deja
    # de hundirse en mercados alcistas. Ver CLAUDE.md.
    timeframe: str = _env("TIMEFRAME", "4h")
    candle_history: int = 300                                   # velas en memoria por símbolo
    default_strategy: str = _env("DEFAULT_STRATEGY", "momentum_4h")
    # BOT_AUTOSTART=1: el bot arranca solo al levantar el proceso. Pensado para
    # despliegues persistentes (Docker/VPS) donde nadie pulsa "Arrancar".
    autostart: bool = _env("AUTOSTART", False)
    # Filtro de régimen: solo abrir largos con BTC por encima de su EMA.
    # Mejoró 24 de 25 configuraciones en el walk-forward.
    use_regime_filter: bool = _env("USE_REGIME_FILTER", True)
    regime_ema: int = _env("REGIME_EMA", 50)

    # Endpoints
    # En Macs corporativos el proxy del sistema devuelve 407; por defecto lo
    # ignoramos y vamos directos. BOT_TRUST_ENV_PROXY=1 para usarlo.
    trust_env_proxy: bool = _env("TRUST_ENV_PROXY", False)
    rest_base: str = "https://api.binance.com"
    ws_base: str = "wss://stream.binance.com:443"
    testnet_rest_base: str = "https://testnet.binance.vision"
    testnet_api_key: str = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    testnet_api_secret: str = os.environ.get("BINANCE_TESTNET_API_SECRET", "")

    # Resultados de validación: van VERSIONADOS en el repo (backend/validation),
    # no en data/, porque data/ es un volumen vacío en Docker y el panel se
    # quedaría en blanco al desplegar. Son datos de referencia, no estado.
    validation_dir: str = _env("VALIDATION_DIR",
                               os.path.join(os.path.dirname(__file__), "..", "validation"))
    validation_experiment_file: str = _env("VALIDATION_EXPERIMENT", "experiment_4h.json")
    validation_holdout_file: str = _env("VALIDATION_HOLDOUT", "holdout_4h.json")

    # Persistencia
    db_path: str = _env("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "bot.db"))
    data_dir: str = _env("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))


settings = Settings()

TIMEFRAME_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
}
