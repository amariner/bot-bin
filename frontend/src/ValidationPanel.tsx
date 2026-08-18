import { useEffect, useState } from 'react'

interface Metrics {
  return_pct: number
  profit_factor: number | null
  trades: number
  max_drawdown_pct: number
  win_rate_pct?: number
  positive_days_pct?: number
  name?: string
}

interface RobustRow {
  name: string
  train: Metrics
  select: Metrics
}

interface Experiment {
  available: boolean
  symbols?: number
  timeframe?: string
  days?: number
  fee?: number
  periods?: { train: [number, number]; select: [number, number]; holdout: [number, number] }
  benchmark?: { train: { return_pct: number }; select: { return_pct: number } }
  robust?: RobustRow[]
  train_top?: (Metrics & { name: string })[]
}

interface Holdout {
  available: boolean
  timeframe?: string
  finalists?: string[]
  benchmark_time_holdout?: number
  benchmark_fresh_symbols?: number
  fresh_symbols?: number
  fresh_results?: Record<string, Metrics[]>
  time_holdout_results?: Record<string, Metrics[]>
  verdict?: 'pass' | 'fail'
}

/** Veredicto con matices: "positiva en todo" y "bate al mercado en todo" son
 *  cosas distintas, y mezclarlas engaña. */
function verdictOf(hold: Holdout | null) {
  const fresh = hold?.fresh_results?.['0.00075'] ?? []
  const time = hold?.time_holdout_results?.['0.00075'] ?? []
  if (!fresh.length || !time.length) return null
  const bhF = hold?.benchmark_fresh_symbols ?? 0
  const bhT = hold?.benchmark_time_holdout ?? 0
  const byName = new Map(time.map((r) => [r.name, r]))
  const best = fresh
    .map((f) => ({ f, t: byName.get(f.name) }))
    .filter((x) => x.t)
    .sort((a, b) => (b.f.return_pct + (b.t?.return_pct ?? 0)) - (a.f.return_pct + (a.t?.return_pct ?? 0)))[0]
  if (!best) return null
  const positiveBoth = best.f.return_pct > 0 && (best.t?.return_pct ?? 0) > 0
  const beatsBoth = best.f.return_pct > bhF && (best.t?.return_pct ?? 0) > bhT
  return { best, positiveBoth, beatsBoth, bhF, bhT }
}

const d = (ts: number) =>
  new Date(ts).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: '2-digit' })
const n = (v: number | null | undefined, dec = 2) =>
  v === null || v === undefined ? '–' : v.toLocaleString('es-ES', { minimumFractionDigits: dec, maximumFractionDigits: dec })
const cls = (v: number | null | undefined) => (v == null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '')

export function ValidationPanel() {
  const [exp, setExp] = useState<Experiment | null>(null)
  const [hold, setHold] = useState<Holdout | null>(null)

  useEffect(() => {
    const load = () => {
      fetch('/api/experiment').then((r) => r.json()).then(setExp).catch(() => {})
      fetch('/api/holdout').then((r) => r.json()).then(setHold).catch(() => {})
    }
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  if (!exp) return <p className="empty">Cargando…</p>
  if (!exp.available)
    return (
      <div className="empty">
        <p>Aún no se ha ejecutado la búsqueda de configuración.</p>
        <code>cd backend &amp;&amp; .venv/bin/python scripts/experiment.py --symbols 40 --days 240</code>
      </div>
    )

  const bhTrain = exp.benchmark?.train.return_pct ?? 0
  const bhSelect = exp.benchmark?.select.return_pct ?? 0
  const freshTaker = hold?.fresh_results?.['0.001'] ?? []
  const freshBnb = hold?.fresh_results?.['0.00075'] ?? []
  const timeBnb = hold?.time_holdout_results?.['0.00075'] ?? []
  const verdict = verdictOf(hold)

  return (
    <div className="backtest">
      {verdict && (
        <div className={`verdict ${verdict.beatsBoth ? 'ok' : verdict.positiveBoth ? 'warn' : 'bad'}`}>
          <strong>
            {verdict.beatsBoth
              ? '✅ Bate al mercado en las dos pruebas finales'
              : verdict.positiveBoth
                ? '✅ Positiva en las dos pruebas finales, con un matiz'
                : '❌ La ventaja no generaliza'}
          </strong>
          <span>
            <b>{verdict.best.f.name}</b> · en un periodo posterior nunca usado ganó{' '}
            <b className={cls(verdict.best.t?.return_pct)}>{n(verdict.best.t?.return_pct)}%</b>{' '}
            (mercado {n(verdict.bhT)}%) y en {hold?.fresh_symbols} monedas que jamás
            intervinieron en ningún ajuste ganó{' '}
            <b className={cls(verdict.best.f.return_pct)}>{n(verdict.best.f.return_pct)}%</b>{' '}
            (mercado {n(verdict.bhF)}%).
            {!verdict.beatsBoth && verdict.positiveBoth && (
              <> El matiz: gana dinero siempre, pero en el tramo fuertemente alcista
              rinde menos que simplemente comprar y mantener. Protege en las caídas
              a cambio de ceder algo en las subidas.</>
            )}
          </span>
        </div>
      )}

      <div className="periods">
        <div>
          <span className="dim">1 · Búsqueda (train)</span>
          <b>{exp.periods && `${d(exp.periods.train[0])} → ${d(exp.periods.train[1])}`}</b>
          <span className={`dim ${cls(bhTrain)}`}>mercado {n(bhTrain)}%</span>
        </div>
        <div>
          <span className="dim">2 · Selección (select)</span>
          <b>{exp.periods && `${d(exp.periods.select[0])} → ${d(exp.periods.select[1])}`}</b>
          <span className={`dim ${cls(bhSelect)}`}>mercado {n(bhSelect)}%</span>
        </div>
        <div>
          <span className="dim">3 · Test final (holdout)</span>
          <b>{exp.periods && `${d(exp.periods.holdout[0])} → ${d(exp.periods.holdout[1])}`}</b>
          <span className="dim">+ {hold?.fresh_symbols ?? '?'} monedas nuevas</span>
        </div>
      </div>

      <h3>Configuraciones robustas — ganan en los dos primeros periodos</h3>
      {exp.robust && exp.robust.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Configuración</th>
              <th>Train</th>
              <th>vs mercado</th>
              <th>Select</th>
              <th>vs mercado</th>
              <th>PF select</th>
              <th>Trades</th>
            </tr>
          </thead>
          <tbody>
            {exp.robust.map((r) => (
              <tr key={r.name}>
                <td className="sym">{r.name}</td>
                <td className={cls(r.train.return_pct)}>{n(r.train.return_pct)}%</td>
                <td className="dim">{n(r.train.return_pct - bhTrain)}</td>
                <td className={cls(r.select.return_pct)}>{n(r.select.return_pct)}%</td>
                <td className="dim">{n(r.select.return_pct - bhSelect)}</td>
                <td>{n(r.select.profit_factor)}</td>
                <td className="dim">{r.select.trades}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty">Ninguna configuración fue robusta en dos periodos.</p>
      )}

      {timeBnb.length > 0 && (
        <>
          <h3>
            Test final A · periodo posterior nunca usado — mercado{' '}
            <span className={cls(hold?.benchmark_time_holdout)}>
              {n(hold?.benchmark_time_holdout)}%
            </span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Configuración</th><th>Retorno</th><th>vs mercado</th>
                <th>PF</th><th>maxDD</th><th>Trades</th>
              </tr>
            </thead>
            <tbody>
              {timeBnb.map((r) => (
                <tr key={r.name}>
                  <td className="sym">{r.name}</td>
                  <td className={cls(r.return_pct)}>{n(r.return_pct)}%</td>
                  <td className="dim">{n(r.return_pct - (hold?.benchmark_time_holdout ?? 0))}</td>
                  <td>{n(r.profit_factor)}</td>
                  <td className="dim">{n(r.max_drawdown_pct)}%</td>
                  <td className="dim">{r.trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {freshBnb.length > 0 && (
        <>
          <h3>
            Test final B · {hold?.fresh_symbols} monedas nunca usadas — mercado{' '}
            <span className={cls(hold?.benchmark_fresh_symbols)}>
              {n(hold?.benchmark_fresh_symbols)}%
            </span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Configuración</th>
                <th>Comisión 0,100%</th>
                <th>Comisión 0,075% (BNB)</th>
                <th>PF</th>
                <th>maxDD</th>
                <th>Trades</th>
              </tr>
            </thead>
            <tbody>
              {freshBnb.map((r, i) => (
                <tr key={r.name}>
                  <td className="sym">{r.name}</td>
                  <td className={cls(freshTaker[i]?.return_pct)}>
                    {n(freshTaker[i]?.return_pct)}%
                  </td>
                  <td className={cls(r.return_pct)}>{n(r.return_pct)}%</td>
                  <td>{n(r.profit_factor)}</td>
                  <td className="dim">{n(r.max_drawdown_pct)}%</td>
                  <td className="dim">{r.trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <p className="note">
        Método: la rejilla completa se explora en <b>train</b>; las que ganan se reprueban en{' '}
        <b>select</b> para descartar sobreajuste; y solo las supervivientes pasan al{' '}
        <b>test final</b>, que usa un periodo posterior <b>y monedas distintas</b>. Todo se
        compara contra comprar y mantener: ganar menos que el mercado no es ganar.
      </p>
    </div>
  )
}
