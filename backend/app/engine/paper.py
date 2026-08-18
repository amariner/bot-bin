"""Motor de paper trading: simula fills de órdenes de mercado contra el precio
real, aplicando slippage y comisiones. Misma aritmética en backtest y en vivo."""
from dataclasses import dataclass

from ..config import settings


@dataclass
class Fill:
    price: float      # precio efectivo tras slippage
    qty: float        # cantidad de base asset
    notional: float   # qty * price
    fee: float        # comisión en USDT


class PaperBroker:
    def __init__(self, fee_rate: float = None, slippage_bps: float = None):
        self.fee_rate = settings.fee_rate if fee_rate is None else fee_rate
        self.slippage_bps = settings.slippage_bps if slippage_bps is None else slippage_bps

    def _slip(self, price: float, side: str) -> float:
        s = self.slippage_bps / 10_000
        return price * (1 + s) if side == "buy" else price * (1 - s)

    def buy(self, notional: float, market_price: float) -> Fill:
        """Compra a mercado gastando `notional` USDT."""
        price = self._slip(market_price, "buy")
        qty = notional / price
        fee = notional * self.fee_rate
        return Fill(price=price, qty=qty, notional=notional, fee=fee)

    def sell(self, qty: float, market_price: float) -> Fill:
        """Vende `qty` del activo a mercado."""
        price = self._slip(market_price, "sell")
        notional = qty * price
        fee = notional * self.fee_rate
        return Fill(price=price, qty=qty, notional=notional, fee=fee)
