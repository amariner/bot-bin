export interface PositionDto {
  symbol: string
  qty: number
  entry_price: number
  stop_price: number
  take_profit: number
  opened_ts: number
  strategy: string
  reason: string
  bars_held: number
  peak?: number | null
  last_price?: number
  unrealized_pnl?: number
  unrealized_pct?: number
  stop_distance_pct?: number
}

export interface EventDto {
  ts: number
  type: string
  text: string
}

export interface NearSignalDto {
  symbol: string
  dist_to_breakout_pct: number
  breakout_level: number
  last_close: number
  vol_ratio: number
  vol_needed: number
  in_position: boolean
}

export interface TradeDto {
  symbol: string
  side: string
  qty: number
  entry_price: number
  exit_price: number
  entry_ts: number
  exit_ts: number
  pnl: number
  fees: number
  strategy: string
  entry_reason: string
  exit_reason: string
}

export interface MoverDto {
  symbol: string
  base: string
  last_price: number
  change_pct: number
  quote_volume: number
}

export interface BotState {
  type: 'state'
  ts: number
  status: 'stopped' | 'warming_up' | 'running' | 'error'
  error: string | null
  strategy: string
  started_at: number | null
  stream_connected: boolean
  timeframe: string
  next_close_ts: number
  candles_processed: number
  signals_seen: number
  signals_rejected: number
  last_candle_ts: number | null
  regime_filter: boolean
  regime_risk_on: boolean | null
  equity: number
  cash: number
  initial_capital: number
  total_return_pct: number
  daily_pnl_pct: number
  circuit_breaker: boolean
  open_positions: PositionDto[]
  session_trades: TradeDto[]
  universe_size: number
  top_movers: MoverDto[]
  bottom_movers: MoverDto[]
  recent_events: EventDto[]
  near_signals: NearSignalDto[]
  max_positions: number
  eur_rate: number | null
}
