from app.universe import filter_universe


def tick(sym, vol, change=1.0, price=1.0):
    return {"symbol": sym, "lastPrice": str(price), "priceChangePercent": str(change),
            "quoteVolume": str(vol)}


def test_filters_and_sorts_by_volume():
    tickers = [
        tick("BTCUSDT", 1_000_000),
        tick("ETHUSDT", 2_000_000),
        tick("USDCUSDT", 9_000_000),    # stablecoin: fuera
        tick("BTCUPUSDT", 5_000_000),   # token apalancado: fuera
        tick("DOGEBTC", 3_000_000),     # no es par USDT: fuera
        tick("XRPUSDT", 500_000),
        tick("DELISTUSDT", 800_000),    # no está en TRADING: fuera
    ]
    trading = {"BTCUSDT", "ETHUSDT", "USDCUSDT", "BTCUPUSDT", "XRPUSDT"}
    rows = filter_universe(tickers, trading, size=10)
    symbols = [r["symbol"] for r in rows]
    assert symbols == ["ETHUSDT", "BTCUSDT", "XRPUSDT"]


def test_respects_size_limit():
    tickers = [tick(f"AAA{i}USDT", 1000 + i) for i in range(20)]
    trading = {t["symbol"] for t in tickers}
    rows = filter_universe(tickers, trading, size=5)
    assert len(rows) == 5
    assert rows[0]["quote_volume"] == 1019
