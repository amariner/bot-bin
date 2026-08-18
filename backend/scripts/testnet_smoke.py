"""Smoke test de integración con el Spot Testnet de Binance.

Requiere claves de https://testnet.binance.vision en las variables de entorno
BINANCE_TESTNET_API_KEY y BINANCE_TESTNET_API_SECRET.

Uso:
    python -m scripts.testnet_smoke            # consulta la cuenta
    python -m scripts.testnet_smoke --order    # además compra 10 USDT de BTC
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.binance_client import BinanceTestnet


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", action="store_true", help="envía una orden de mercado de prueba")
    args = ap.parse_args()

    client = BinanceTestnet()
    if not client.configured:
        print("Faltan BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET.")
        print("Créalas gratis en https://testnet.binance.vision (login con GitHub).")
        return
    try:
        acct = await client.account()
        balances = [b for b in acct["balances"] if float(b["free"]) > 0]
        print("Cuenta testnet OK. Balances:")
        for b in balances[:10]:
            print(f"  {b['asset']}: {b['free']}")
        if args.order:
            print("\nEnviando orden de mercado: compra 10 USDT de BTCUSDT...")
            result = await client.market_order("BTCUSDT", "BUY", 10.0)
            print(f"Orden {result['orderId']} {result['status']}: "
                  f"{result.get('executedQty')} BTC")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
