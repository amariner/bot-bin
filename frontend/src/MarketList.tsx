import { useState } from 'react'
import { Coin } from './CoinIcon'
import type { MoverDto } from './types'

const fmt = (n: number, d = 2) =>
  n.toLocaleString('es-ES', { minimumFractionDigits: d, maximumFractionDigits: d })

const fmtPrice = (n: number) => (n >= 100 ? fmt(n, 2) : n >= 1 ? fmt(n, 4) : fmt(n, 6))

const fmtVol = (v: number) =>
  v >= 1e9 ? `${fmt(v / 1e9, 1)} B` : v >= 1e6 ? `${fmt(v / 1e6, 0)} M` : `${fmt(v / 1e3, 0)} K`

/** Listado de monedas: una fila por moneda, más legible que las tarjetas. */
function MoverRows({ rows, empty }: { rows: MoverDto[]; empty: string }) {
  if (rows.length === 0) return <p className="empty">{empty}</p>
  return (
    <ul className="market-list">
      {rows.map((m) => (
        <li key={m.symbol}>
          <Coin symbol={m.symbol} size={20} />
          <span className="ml-price">{fmtPrice(m.last_price)}</span>
          <span className="ml-vol">{m.quote_volume ? fmtVol(m.quote_volume) : ''}</span>
          <span className={`ml-chg ${m.change_pct > 0 ? 'pos' : m.change_pct < 0 ? 'neg' : ''}`}>
            {m.change_pct > 0 ? '+' : ''}{fmt(m.change_pct, 1)}%
          </span>
        </li>
      ))}
    </ul>
  )
}

interface SectionProps {
  title: string
  subtitle?: string
  defaultOpen?: boolean
  children: React.ReactNode
}

/** Bloque plegable: permite tener varias listas sin llenar la pantalla. */
export function Accordion({ title, subtitle, defaultOpen = false, children }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`acc ${open ? 'open' : ''}`}>
      <button className="acc-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="acc-caret">{open ? '▾' : '▸'}</span>
        <span className="acc-title">{title}</span>
        {subtitle && <span className="acc-sub">{subtitle}</span>}
      </button>
      {open && <div className="acc-body">{children}</div>}
    </div>
  )
}

export function MarketPanel({ state }: {
  state: {
    top_movers: MoverDto[]; bottom_movers: MoverDto[]
    weekly_top: MoverDto[]; weekly_bottom: MoverDto[]
  } | null
}) {
  return (
    <>
      <Accordion title="Hoy" subtitle="últimas 24 horas" defaultOpen>
        <h4>Las que más suben</h4>
        <MoverRows rows={state?.top_movers ?? []} empty="Sin datos todavía" />
        <h4>Las que más bajan</h4>
        <MoverRows rows={state?.bottom_movers ?? []} empty="Sin datos todavía" />
      </Accordion>

      <Accordion title="Las monedas de la semana" subtitle="últimos 7 días">
        <h4>Las que más suben</h4>
        <MoverRows
          rows={state?.weekly_top ?? []}
          empty="Necesita una semana de histórico cargado; arranca el bot y espera unos segundos."
        />
        <h4>Las que más bajan</h4>
        <MoverRows rows={state?.weekly_bottom ?? []} empty="Sin datos todavía" />
      </Accordion>
    </>
  )
}
