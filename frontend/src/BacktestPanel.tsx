import { useEffect, useState } from 'react'
import { EquityChart } from './EquityChart'

interface Metrics {
  return_pct: number
  max_drawdown_pct: number
  trades: number
  win_rate_pct: number
  profit_factor: number | null
  positive_days_pct: number
  total_fees: number
}

interface Candidate {
  name: string
  in_sample: Metrics
  out_sample: Metrics
}

interface WalkforwardData {
  available: boolean
  generated_at?: number
  timeframe?: string
  days?: number
  symbols?: number
  survivors?: number
  in_sample_range?: [number, number]
  out_sample_range?: [number, number]
  candidates?: Candidate[]
  best?: {
    name: string
    regime_filter: boolean
    out_sample_equity_curve: { ts: number; equity: number }[]
    out_sample_metrics: Metrics & { initial_capital: number }
  }
}

const d = (ts: number) => new Date(ts).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: '2-digit' })
const n = (v: number | null | undefined, dec = 2) =>
  v === null || v === undefined ? '–' : v.toLocaleString('es-ES', { minimumFractionDigits: dec, maximumFractionDigits: dec })
const cls = (v: number) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '')

export function BacktestPanel() {
  const [data, setData] = useState<WalkforwardData | null>(null)

  useEffect(() => {
    const load = () => fetch('/api/walkforward').then((r) => r.json()).then(setData).catch(() => {})
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  if (!data) return <p className="empty">Cargando validación…</p>
  if (!data.available)
    return (
      <div className="empty">
        <p>Aún no se ha ejecutado la validación fuera de muestra.</p>
        <code>cd backend &amp;&amp; .venv/bin/python scripts/walkforward.py --symbols 40 --days 240</code>
      </div>
    )

  const survived = (data.survivors ?? 0) > 0
  const best = data.best

  return (
    <div className="backtest">
      <div className={`verdict ${survived ? 'ok' : 'bad'}`}>
        <strong>{survived ? '✅ Ventaja con indicios' : '❌ Sin ventaja demostrada'}</strong>
        <span>
          {survived
            ? `${data.survivors} de ${data.candidates?.length} configuraciones ganadoras siguen siéndolo en datos no vistos.`
            : `Ninguna de las ${data.candidates?.length} configuraciones ganadoras en el periodo de búsqueda sobrevive en datos no vistos: era sobreajuste. No pasar a dinero real.`}
        </span>
      </div>

      <div className="periods">
        <div>
          <span className="dim">Búsqueda (in-sample)</span>
          <b>{data.in_sample_range && `${d(data.in_sample_range[0])} → ${d(data.in_sample_range[1])}`}</b>
        </div>
        <div>
          <span className="dim">Validación (out-of-sample)</span>
          <b>{data.out_sample_range && `${d(data.out_sample_range[0])} → ${d(data.out_sample_range[1])}`}</b>
        </div>
        <div>
          <span className="dim">Datos</span>
          <b>{data.symbols} símbolos · {data.timeframe} · {data.days} días</b>
        </div>
      </div>

      {best && (
        <>
          <h3>Curva de equity en el periodo de validación — {best.name}</h3>
          <EquityChart
            history={best.out_sample_equity_curve}
            baseline={best.out_sample_metrics.initial_capital}
            height={220}
          />
        </>
      )}

      <h3>Comparativa búsqueda vs validación</h3>
      <table>
        <thead>
          <tr>
            <th>Configuración</th>
            <th>Ret. búsqueda</th>
            <th>PF búsq.</th>
            <th>Ret. validación</th>
            <th>PF valid.</th>
            <th>maxDD valid.</th>
            <th>Trades</th>
          </tr>
        </thead>
        <tbody>
          {data.candidates?.map((c) => (
            <tr key={c.name}>
              <td className="sym">{c.name}</td>
              <td className={cls(c.in_sample.return_pct)}>{n(c.in_sample.return_pct)}%</td>
              <td>{n(c.in_sample.profit_factor)}</td>
              <td className={cls(c.out_sample.return_pct)}>{n(c.out_sample.return_pct)}%</td>
              <td>{n(c.out_sample.profit_factor)}</td>
              <td className="dim">{n(c.out_sample.max_drawdown_pct)}%</td>
              <td className="dim">{c.out_sample.trades}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Una configuración solo es creíble si gana en <b>ambas</b> columnas. Ganar solo en la
        de búsqueda significa que se ajustó al ruido del pasado.
      </p>
    </div>
  )
}
