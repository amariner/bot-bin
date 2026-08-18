"""Contrato de estrategia. El motor (backtest o vivo) llama a check_entry con el
histórico de velas CERRADAS de un símbolo; la gestión de stop/take-profit/tiempo
la aplica el motor con lo que devuelva la señal. check_exit permite salidas
adicionales propias de la estrategia."""
from typing import List, Optional

from ..models import Candle, Position, Signal


class Strategy:
    name = "base"
    warmup = 50  # velas mínimas antes de poder evaluar

    def check_entry(self, symbol: str, candles: List[Candle]) -> Optional[Signal]:
        raise NotImplementedError

    def update_position(self, symbol: str, candles: List[Candle], position: Position) -> None:
        """Se llama al cerrar cada vela, ANTES de comprobar salidas. Permite
        mover el stop (trailing) o guardar estado en position.meta."""
        return None

    def check_exit(self, symbol: str, candles: List[Candle], position: Position) -> Optional[str]:
        """Devuelve motivo de salida o None. SL/TP/tiempo los gestiona el motor."""
        return None
