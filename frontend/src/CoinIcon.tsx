import { useState } from 'react'

/**
 * Logo de la moneda. Muchas de las 100 del universo son muy nuevas y no tienen
 * icono en ningún repositorio, así que siempre hay plan B: un círculo de color
 * estable (derivado del propio nombre) con las iniciales.
 */
const PALETTE = [
  '#f7931a', '#627eea', '#26a17b', '#2775ca', '#8247e5', '#e84142',
  '#00d395', '#f0b90b', '#c2a633', '#345d9d', '#ff007a', '#16c784',
]

function colorFor(base: string) {
  let h = 0
  for (let i = 0; i < base.length; i++) h = (h * 31 + base.charCodeAt(i)) >>> 0
  return PALETTE[h % PALETTE.length]
}

export function CoinIcon({ symbol, size = 22 }: { symbol: string; size?: number }) {
  const base = symbol.replace(/USDT$/, '')
  const [failed, setFailed] = useState(false)
  const style = { width: size, height: size, minWidth: size }

  if (!failed) {
    return (
      <img
        className="coin-icon"
        style={style}
        src={`https://cdn.jsdelivr.net/npm/cryptocurrency-icons@0.18.1/svg/color/${base.toLowerCase()}.svg`}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
      />
    )
  }
  return (
    <span
      className="coin-icon coin-fallback"
      style={{ ...style, background: colorFor(base), fontSize: size * 0.38 }}
      aria-hidden="true"
    >
      {base.slice(0, 3)}
    </span>
  )
}

/** Icono + nombre, que es como aparece la moneda en casi todas las tablas. */
export function Coin({ symbol, size = 22 }: { symbol: string; size?: number }) {
  return (
    <span className="coin">
      <CoinIcon symbol={symbol} size={size} />
      <b>{symbol.replace(/USDT$/, '')}</b>
    </span>
  )
}
