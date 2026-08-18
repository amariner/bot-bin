import { useCallback, useEffect, useState } from 'react'

interface EventRow { ts: number; type: string; payload: Record<string, unknown> }

interface Analysis {
  horas_analizadas: number
  estado_actual: Record<string, unknown>
  eventos_por_tipo: Record<string, number>
  motivos_de_descarte: Record<string, number>
  monedas_con_mas_señales: { symbol: string; señales: number; compradas: number; descartadas: number }[]
  operaciones: {
    total: number; ganadoras: number; perdedoras: number; acierto_pct: number
    pnl_total: number; pnl_medio: number; ganancia_media: number; perdida_media: number
    profit_factor: number | null; comisiones: number; horas_medias_en_cartera: number
    por_motivo_de_salida: Record<string, number>
    mejor: { symbol: string; pnl: number } | null
    peor: { symbol: string; pnl: number } | null
  }
  capital: { muestras: number; inicial: number | null; actual: number | null; maximo: number | null; peor_bache_pct: number }
  conclusiones: string[]
}

const FILTROS = [
  { id: '', label: 'Todo' },
  { id: 'open,close', label: 'Compras y ventas' },
  { id: 'signal_skipped', label: 'Descartadas' },
  { id: 'start,stop', label: 'Arranques' },
]

const fecha = (ts: number) =>
  new Date(ts).toLocaleString('es-ES', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })

const icono = (t: string) =>
  t === 'open' ? '🟢' : t === 'close' ? '🔴' : t === 'signal_skipped' ? '⏭️'
    : t === 'start' ? '▶️' : t === 'stop' ? '⏹️' : '·'

const n = (v: number | null | undefined, d = 2) =>
  v == null ? '–' : v.toLocaleString('es-ES', { minimumFractionDigits: d, maximumFractionDigits: d })

export function LogPanel() {
  const [rows, setRows] = useState<EventRow[]>([])
  const [ana, setAna] = useState<Analysis | null>(null)
  const [filtro, setFiltro] = useState('')
  const [auto, setAuto] = useState(true)

  const cargar = useCallback(() => {
    const q = filtro ? `&type=${filtro}` : ''
    fetch(`/api/events?limit=300${q}`).then((r) => r.json()).then(setRows).catch(() => {})
    fetch('/api/analysis').then((r) => r.json()).then(setAna).catch(() => {})
  }, [filtro])

  useEffect(() => {
    cargar()
    if (!auto) return
    const id = setInterval(cargar, 15_000)
    return () => clearInterval(id)
  }, [cargar, auto])

  const o = ana?.operaciones

  return (
    <div className="logpanel">
      {ana && (
        <>
          <div className="card">
            <h2>Conclusiones automáticas</h2>
            <ul className="conclusiones">
              {ana.conclusiones.map((c, i) => (
                <li key={i} className={c.startsWith('AJUSTE') ? 'ajuste' : c.startsWith('AVISO') || c.startsWith('OJO') ? 'aviso' : ''}>
                  {c}
                </li>
              ))}
            </ul>
            <p className="note">
              Se recalculan solas con el registro acumulado. Con velas de 4 horas hacen
              falta días para que sean fiables — antes de 30 operaciones son orientativas.
            </p>
          </div>

          <div className="grid">
            <div className="card">
              <h2>Por qué no compra más</h2>
              {Object.keys(ana.motivos_de_descarte).length === 0 ? (
                <p className="empty">Todavía no ha descartado ninguna señal.</p>
              ) : (
                <ul className="market-list">
                  {Object.entries(ana.motivos_de_descarte).map(([motivo, veces]) => (
                    <li key={motivo}>
                      <span>{motivo}</span>
                      <span /><span />
                      <span className="ml-chg dim">{veces}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="card">
              <h2>Resultados</h2>
              {o && o.total > 0 ? (
                <ul className="market-list">
                  <li><span>Operaciones cerradas</span><span /><span /><span className="ml-chg">{o.total}</span></li>
                  <li><span>Acierto</span><span /><span /><span className="ml-chg">{n(o.acierto_pct, 1)}%</span></li>
                  <li><span>Resultado total</span><span /><span /><span className={`ml-chg ${o.pnl_total > 0 ? 'pos' : o.pnl_total < 0 ? 'neg' : ''}`}>{n(o.pnl_total)} USDT</span></li>
                  <li><span>Profit factor</span><span /><span /><span className="ml-chg">{n(o.profit_factor)}</span></li>
                  <li><span>Ganancia media / pérdida media</span><span /><span /><span className="ml-chg">{n(o.ganancia_media)} / {n(o.perdida_media)}</span></li>
                  <li><span>Comisiones pagadas</span><span /><span /><span className="ml-chg dim">{n(o.comisiones)} USDT</span></li>
                  <li><span>Horas medias en cartera</span><span /><span /><span className="ml-chg dim">{n(o.horas_medias_en_cartera, 1)}</span></li>
                  <li><span>Peor bache del capital</span><span /><span /><span className="ml-chg neg">{n(ana.capital.peor_bache_pct)}%</span></li>
                </ul>
              ) : (
                <p className="empty">Sin operaciones cerradas todavía.</p>
              )}
            </div>
          </div>
        </>
      )}

      <div className="card">
        <div className="log-head">
          <h2>Registro completo</h2>
          <div className="log-filtros">
            {FILTROS.map((f) => (
              <button key={f.id} className={filtro === f.id ? 'tab on' : 'tab'}
                      onClick={() => setFiltro(f.id)}>{f.label}</button>
            ))}
            <label className="log-auto">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              actualizar solo
            </label>
          </div>
        </div>
        {rows.length === 0 ? (
          <p className="empty">Sin entradas para este filtro.</p>
        ) : (
          <div className="feed log-feed">
            {rows.map((r, i) => (
              <div key={`${r.ts}-${i}`} className="feed-row">
                <span className="dim feed-time">{fecha(r.ts)}</span>
                <span>{icono(r.type)} {String(r.payload?.text ?? r.type)}</span>
              </div>
            ))}
          </div>
        )}
        <p className="note">{rows.length} entradas · el registro vive en la base de datos, así que sobrevive a reinicios y actualizaciones.</p>
      </div>
    </div>
  )
}
