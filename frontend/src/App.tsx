import { useCallback, useEffect, useState } from 'react'
import { BacktestPanel } from './BacktestPanel'
import { Coin } from './CoinIcon'
import { EquityChart } from './EquityChart'
import { Narrator } from './Narrator'
import { ValidationPanel } from './ValidationPanel'
import { useBotSocket } from './useBotSocket'
import type { BotState, EventDto, MoverDto, NearSignalDto, PositionDto, TradeDto } from './types'
import './App.css'

const fmt = (n: number | undefined | null, d = 2) =>
  n === undefined || n === null ? '–' : n.toLocaleString('es-ES', { minimumFractionDigits: d, maximumFractionDigits: d })

const fmtPrice = (n: number) => (n >= 100 ? fmt(n, 2) : n >= 1 ? fmt(n, 4) : fmt(n, 6))

/** Se opera en USDT (Tether), la moneda con liquidez real en Binance. */
const usdt = (n: number | undefined | null, d = 2) => `${fmt(n, d)} USDT`

/** Equivalente aproximado en euros, solo informativo. */
const enEuros = (n: number | undefined | null, rate: number | null | undefined) =>
  n == null || !rate ? null : `≈ ${fmt(n / rate, 2)} €`

const fmtTime = (ts: number) =>
  new Date(ts).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })

const pnlClass = (v: number) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '')

function Countdown({ target }: { target: number | undefined }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  if (!target) return <>–</>
  const left = Math.max(0, target - now)
  const m = Math.floor(left / 60000)
  const s = Math.floor((left % 60000) / 1000)
  return <>{m}m {String(s).padStart(2, '0')}s</>
}

function StatusPill({ state, wsConnected }: { state: BotState | null; wsConnected: boolean }) {
  if (!wsConnected) return <span className="pill err">sin conexión al backend</span>
  const s = state?.status ?? 'stopped'
  const label = { stopped: 'parado', warming_up: 'calentando…', running: 'en marcha', error: 'error' }[s]
  const extra = s === 'running' && !state?.stream_connected ? ' · reconectando stream' : ''
  return <span className={`pill ${s}`}>{label}{extra}</span>
}

function Controls({ state, onChanged }: { state: BotState | null; onChanged: () => void }) {
  const [strategies, setStrategies] = useState<string[]>([])
  const [strategy, setStrategy] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/api/strategies').then((r) => r.json()).then((d) => {
      setStrategies(d.available)
      setStrategy(d.default)
    })
  }, [])

  const running = state?.status === 'running' || state?.status === 'warming_up'

  const start = async () => {
    setBusy(true)
    await fetch('/api/bot/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy }),
    })
    setBusy(false)
    onChanged()
  }
  const stop = async () => {
    setBusy(true)
    await fetch('/api/bot/stop?liquidate=true', { method: 'POST' })
    setBusy(false)
    onChanged()
  }

  return (
    <div className="controls">
      <select value={strategy} disabled={running} onChange={(e) => setStrategy(e.target.value)}>
        {strategies.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      {running
        ? <button className="btn stop" disabled={busy} onClick={stop}>■ Parar</button>
        : <button className="btn start" disabled={busy || !strategy} onClick={start}>▶ Arrancar</button>}
    </div>
  )
}

function Stat({ label, value, cls, sub }: { label: string; value: string; cls?: string; sub?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${cls ?? ''}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

function Positions({ rows }: { rows: PositionDto[] }) {
  if (rows.length === 0)
    return (
      <p className="empty">
        Sin posiciones abiertas. Se abrirá una cuando, al cierre de una vela, alguna
        moneda rompa su máximo de 20 velas con 4× su volumen medio y BTC esté en verde.
      </p>
    )
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Moneda</th><th>Compró a</th><th>Ahora</th><th>Máximo</th>
              <th>Vende si baja a</th><th>Margen</th><th>Ganancia</th><th>Desde</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.symbol}>
                <td><Coin symbol={p.symbol} /></td>
                <td>{fmtPrice(p.entry_price)}</td>
                <td>{p.last_price ? fmtPrice(p.last_price) : '–'}</td>
                <td className="dim">{p.peak ? fmtPrice(p.peak) : '–'}</td>
                <td className="dim">{fmtPrice(p.stop_price)}</td>
                <td className="dim">
                  {p.stop_distance_pct != null ? `${fmt(p.stop_distance_pct, 1)}%` : '–'}
                </td>
                <td className={pnlClass(p.unrealized_pnl ?? 0)}>
                  {fmt(p.unrealized_pnl)} USDT ({fmt(p.unrealized_pct)}%)
                </td>
                <td className="dim">{fmtTime(p.opened_ts)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">
        <b>Vende si baja a</b> es el precio de venta automática, que sube solo conforme
        sube la moneda. <b>Margen</b> es cuánto puede caer antes de que la venda.
      </p>
    </>
  )
}

/** Feed de actividad: qué ha hecho el bot y por qué, en orden cronológico inverso. */
function ActivityFeed({ live }: { live: EventDto[] }) {
  const [history, setHistory] = useState<EventDto[]>([])
  useEffect(() => {
    fetch('/api/events?limit=60')
      .then((r) => r.json())
      .then((rows: { ts: number; type: string; payload: Record<string, unknown> }[]) =>
        setHistory(rows.map((r) => ({
          ts: r.ts, type: r.type,
          text: typeof r.payload?.text === 'string' ? (r.payload.text as string) : r.type,
        }))))
      .catch(() => {})
  }, [])
  // los eventos en vivo del websocket tienen prioridad; el historial rellena
  const seen = new Set(live.map((e) => `${e.ts}-${e.text}`))
  const rows = [...live, ...history.filter((e) => !seen.has(`${e.ts}-${e.text}`))].slice(0, 40)
  if (rows.length === 0)
    return <p className="empty">Aún sin actividad. Cada compra, venta o señal descartada aparecerá aquí.</p>
  const icon = (t: string) =>
    t === 'open' ? '🟢' : t === 'close' ? '🔴' : t === 'signal_skipped' ? '⏭️' : '·'
  return (
    <div className="feed">
      {rows.map((e, i) => (
        <div key={`${e.ts}-${i}`} className="feed-row">
          <span className="dim feed-time">
            {new Date(e.ts).toLocaleString('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
          </span>
          <span>{icon(e.type)} {e.text}</span>
        </div>
      ))}
    </div>
  )
}

/** Qué está vigilando: monedas a punto de cumplir la condición de entrada. */
function NearSignals({ rows, timeframe }: { rows: NearSignalDto[]; timeframe: string }) {
  if (rows.length === 0)
    return (
      <p className="empty">
        Ninguna moneda está a menos de un 3% de romper su máximo de 20 velas ahora mismo.
      </p>
    )
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Moneda</th><th>Le falta subir</th><th>Precio a superar</th>
              <th>Volumen (necesita 4×)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td>
                  <Coin symbol={r.symbol} />{r.in_position ? ' 📌' : ''}
                </td>
                <td className={r.dist_to_breakout_pct <= 0 ? 'pos' : ''}>
                  {r.dist_to_breakout_pct <= 0
                    ? 'ya lo supera'
                    : `${fmt(r.dist_to_breakout_pct, 1)}%`}
                </td>
                <td className="dim">{fmtPrice(r.breakout_level)}</td>
                <td className={r.vol_ratio >= r.vol_needed ? 'pos' : 'dim'}>
                  {fmt(r.vol_ratio, 1)}× {r.vol_ratio >= r.vol_needed ? '✓' : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">
        Estas son las monedas que el bot tiene más cerca de comprar. Necesita las
        <b> dos cosas a la vez</b> en la revisión de cada {timeframe === '4h' ? '4 horas' : timeframe}:
        que supere ese precio <b>y</b> que se negocie 4 veces más de lo habitual.
        Casi siempre falla el volumen, por eso compra poco. 📌 = ya la tiene comprada.
      </p>
    </>
  )
}

/** Historial persistente (SQLite): sobrevive a reinicios del proceso. */
function Trades({ sessionCount }: { sessionCount: number }) {
  const [rows, setRows] = useState<TradeDto[]>([])
  useEffect(() => {
    fetch('/api/trades?limit=100').then((r) => r.json()).then(setRows).catch(() => {})
  }, [sessionCount])   // cada operación nueva en vivo refresca el historial
  if (rows.length === 0) return <p className="empty">Aún no hay operaciones cerradas</p>
  const total = rows.reduce((s, t) => s + t.pnl, 0)
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Cuándo</th><th>Moneda</th><th>Compró a</th><th>Vendió a</th>
              <th>Resultado</th><th>Por qué vendió</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => (
              <tr key={`${t.symbol}-${t.exit_ts}-${i}`}>
                <td className="dim">
                  {new Date(t.exit_ts).toLocaleString('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                </td>
                <td><Coin symbol={t.symbol} /></td>
                <td>{fmtPrice(t.entry_price)}</td>
                <td>{fmtPrice(t.exit_price)}</td>
                <td className={pnlClass(t.pnl)}>{fmt(t.pnl)} USDT</td>
                <td className="dim">{t.exit_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">
        {rows.length} operaciones · resultado acumulado{' '}
        <b className={pnlClass(total)}>{fmt(total)} USDT</b>
      </p>
    </>
  )
}

function Movers({ title, rows }: { title: string; rows: MoverDto[] }) {
  return (
    <div className="movers">
      <h3>{title}</h3>
      <div className="movers-grid">
        {rows.map((m) => (
          <div key={m.symbol} className="mover">
            <Coin symbol={m.symbol} size={18} />
            <span className="price">{fmtPrice(m.last_price)}</span>
            <span className={`chg ${pnlClass(m.change_pct)}`}>
              {m.change_pct > 0 ? '+' : ''}{fmt(m.change_pct, 1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Muestra que el bot está vivo aunque no haya operaciones todavía. */
function Diagnostics({ state }: { state: BotState | null }) {
  if (!state || state.status !== 'running') return null
  return (
    <div className="diag">
      <span>Próxima revisión en <b><Countdown target={state.next_close_ts} /></b></span>
      <span>Bitcoin{' '}
        <b className={state.regime_risk_on ? 'pos' : 'neg'}>
          {state.regime_risk_on ? 'fuerte · puede comprar' : 'débil · no compra'}
        </b>
      </span>
      <span>Oportunidades vistas <b>{state.signals_seen}</b></span>
      <span>Descartadas <b>{state.signals_rejected}</b></span>
      <span>Revisiones hechas <b>{state.candles_processed}</b></span>
      {state.eur_rate && <span>1 € = <b>{fmt(state.eur_rate, 3)} USDT</b></span>}
    </div>
  )
}

export default function App() {
  const { state, connected } = useBotSocket()
  const [equityHistory, setEquityHistory] = useState<{ ts: number; equity: number }[]>([])
  const [tab, setTab] = useState<'live' | 'validation' | 'backtest'>('live')

  const loadHistory = useCallback(() => {
    const since = Date.now() - 7 * 86_400_000
    fetch(`/api/equity?since=${since}`).then((r) => r.json()).then(setEquityHistory).catch(() => {})
  }, [])

  useEffect(() => {
    loadHistory()
    const id = setInterval(loadHistory, 30_000)
    return () => clearInterval(id)
  }, [loadHistory])

  const live = state ? { ts: state.ts, equity: state.equity } : null

  return (
    <div className="app">
      <header>
        <div className="brand">
          <h1>bot-bin</h1>
          <span className="dim">paper trading · Binance spot · {state?.universe_size ?? '–'} pares</span>
        </div>
        <StatusPill state={state} wsConnected={connected} />
        {state?.circuit_breaker && <span className="pill err">⛔ circuit breaker −2% día</span>}
        <div className="spacer" />
        <Controls state={state} onChanged={loadHistory} />
      </header>

      {state?.error && <div className="banner-error">{state.error}</div>}

      <Narrator state={state} connected={connected} />

      <section className="stats">
        <Stat label="Dinero total" value={usdt(state?.equity)}
              sub={enEuros(state?.equity, state?.eur_rate)
                   ?? `empezó con ${fmt(state?.initial_capital, 0)}`} />
        <Stat label="Ganancia desde el inicio" value={`${fmt(state?.total_return_pct, 2)}%`}
              cls={pnlClass(state?.total_return_pct ?? 0)}
              sub={usdt((state?.equity ?? 0) - (state?.initial_capital ?? 0))} />
        <Stat label="Hoy" value={`${fmt(state?.daily_pnl_pct, 2)}%`}
              cls={pnlClass(state?.daily_pnl_pct ?? 0)}
              sub="si pierde 2% para de comprar" />
        <Stat label="Sin invertir" value={usdt(state?.cash)}
              sub="dinero libre para comprar" />
        <Stat label="Monedas compradas"
              value={`${state?.open_positions.length ?? 0} de ${state?.max_positions ?? 5}`}
              sub="máximo a la vez" />
      </section>

      <Diagnostics state={state} />

      <div className="tabs">
        <button className={tab === 'live' ? 'tab on' : 'tab'} onClick={() => setTab('live')}>
          En vivo
        </button>
        <button className={tab === 'validation' ? 'tab on' : 'tab'}
                onClick={() => setTab('validation')}>
          Búsqueda de estrategia
        </button>
        <button className={tab === 'backtest' ? 'tab on' : 'tab'} onClick={() => setTab('backtest')}>
          Validación inicial
        </button>
      </div>

      {tab === 'validation' ? (
        <section>
          <div className="card">
            <h2>Búsqueda y validación de estrategia</h2>
            <ValidationPanel />
          </div>
        </section>
      ) : tab === 'live' ? (
        <section className="grid">
          <div className="card chart-card">
            <h2>Curva de equity (sesión en vivo)</h2>
            <EquityChart history={equityHistory} live={live}
                         baseline={state?.initial_capital ?? 10000} />
            {equityHistory.length < 2 && (
              <p className="note">
                El bot solo evalúa entradas al cerrar cada vela de {state?.timeframe ?? '1h'}.
                Hasta la primera operación la curva es plana: es normal, no está roto.
              </p>
            )}
          </div>
          <div className="card">
            <h2>Qué ha ido haciendo</h2>
            <ActivityFeed live={state?.recent_events ?? []} />
          </div>
          <div className="card">
            <h2>Monedas que tiene ahora ({state?.open_positions.length ?? 0} de {state?.max_positions ?? 5})</h2>
            <Positions rows={state?.open_positions ?? []} />
          </div>
          <div className="card">
            <h2>A punto de comprar</h2>
            <NearSignals rows={state?.near_signals ?? []} timeframe={state?.timeframe ?? '4h'} />
          </div>
          <div className="card">
            <h2>Todas las operaciones</h2>
            <Trades sessionCount={state?.session_trades.length ?? 0} />
          </div>
          <div className="card">
            <h2>Cómo va el mercado</h2>
            <Movers title="Las que más suben hoy" rows={state?.top_movers ?? []} />
            <Movers title="Las que más bajan hoy" rows={state?.bottom_movers ?? []} />
          </div>
        </section>
      ) : (
        <section>
          <div className="card">
            <h2>Validación fuera de muestra</h2>
            <BacktestPanel />
          </div>
        </section>
      )}
    </div>
  )
}
