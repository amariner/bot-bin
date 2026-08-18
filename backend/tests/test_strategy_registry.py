import pytest

from app.strategy import PRESETS, describe_strategies, make_strategy
from app.strategy.momentum import MomentumBreakout


def test_all_presets_instantiate():
    for name in PRESETS:
        s = make_strategy(name)
        assert s.name == name
        assert s.warmup > 0


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        make_strategy("no-existe")


def test_momentum_4h_preset_has_validated_params():
    """Blindaje de la configuración GANADORA. Estos valores salen del proceso
    completo (experiment.py 4h → holdout.py → sensitivity.py). Cambiarlos sin
    volver a validar debe romper el test, no colarse en silencio."""
    s = make_strategy("momentum_4h")
    assert isinstance(s, MomentumBreakout)
    assert s.lookback == 20
    assert s.vol_mult == 4.0
    assert s.atr_stop == 2.0
    assert s.trail_atr == 3.0
    assert s.trend_ema == 0        # el filtro de tendencia propia empeoraba en 4h
    assert s.max_bars == 0         # sin stop temporal: el trailing gestiona la salida


def test_default_strategy_and_timeframe_match_validation():
    from app.config import settings
    assert settings.default_strategy == "momentum_4h"
    assert settings.timeframe == "4h", "la ganadora se validó en velas de 4h"
    assert settings.use_regime_filter is True


def test_momentum_trail_preset_kept_for_comparison():
    s = make_strategy("momentum_trail")
    assert isinstance(s, MomentumBreakout)
    assert s.trend_ema == 100


def test_describe_returns_descriptions():
    rows = describe_strategies()
    assert len(rows) == len(PRESETS)
    assert all(r["description"] for r in rows)
