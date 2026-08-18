import type { BotState } from './types'

/**
 * Explica en castellano llano qué está haciendo el bot AHORA. La idea es que
 * alguien que no sepa de trading entienda la pantalla sin preguntar nada.
 */

function faltaPara(ts: number | undefined): string {
  if (!ts) return 'poco'
  const min = Math.max(0, Math.round((ts - Date.now()) / 60000))
  if (min < 60) return `${min} minutos`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h}h ${m}min` : `${h} horas`
}

export function Narrator({ state, connected }: { state: BotState | null; connected: boolean }) {
  if (!connected)
    return (
      <div className="narrator warn">
        <b>Sin conexión con el bot.</b> La página no está recibiendo datos. Si acabas de
        desplegar una versión nueva, espera unos segundos y recarga.
      </div>
    )
  if (!state) return null

  if (state.status === 'stopped')
    return (
      <div className="narrator">
        <b>El bot está parado.</b> No está vigilando el mercado ni puede comprar nada.
        Pulsa <b>Arrancar</b> para ponerlo en marcha.
      </div>
    )

  if (state.status === 'warming_up')
    return (
      <div className="narrator">
        <b>Preparándose…</b> Está descargando el histórico reciente de las 100 monedas
        para poder calcular sus indicadores. Tarda unos segundos.
      </div>
    )

  if (state.status === 'error')
    return (
      <div className="narrator bad">
        <b>Ha habido un problema al arrancar:</b> {state.error}
      </div>
    )

  // ---- en marcha: contamos la situación real
  const pos = state.open_positions.length
  const radar = state.near_signals.length

  if (state.circuit_breaker)
    return (
      <div className="narrator bad">
        <b>Freno de seguridad activado.</b> Hoy el bot ha perdido un 2% del dinero, que
        es el máximo que le permitimos. No comprará nada más hasta mañana, aunque sigue
        vigilando las monedas que ya tiene para venderlas si toca.
      </div>
    )

  const trozos: string[] = []
  trozos.push(
    `Está vigilando las ${state.universe_size} monedas con más movimiento de Binance.`,
  )
  if (pos === 0) {
    trozos.push(
      'Ahora mismo no tiene ninguna comprada: no ha aparecido ninguna oportunidad que cumpla sus condiciones.',
    )
  } else {
    trozos.push(
      `Tiene ${pos} moneda${pos > 1 ? 's' : ''} comprada${pos > 1 ? 's' : ''} de un máximo de ${state.max_positions}.`,
    )
  }
  trozos.push(
    `Revisa todas las monedas cada ${state.timeframe === '4h' ? '4 horas' : state.timeframe}; la próxima revisión es dentro de ${faltaPara(state.next_close_ts)}.`,
  )

  return (
    <div className="narrator">
      <div className="narrator-main">
        <b>¿Qué está pasando?</b> {trozos.join(' ')}
      </div>
      <ul className="narrator-list">
        <li>
          <b>Para comprar</b> espera a que una moneda supere su precio máximo de los
          últimos 3 días con <b>4 veces</b> su volumen habitual de compraventa. Es una
          condición exigente a propósito: prefiere pocas operaciones y buenas.
          {radar > 0 && (
            <> Ahora hay <b>{radar}</b> cerca de conseguirlo (las verás abajo, en el radar).</>
          )}
        </li>
        <li>
          <b>Solo compra si Bitcoin está fuerte.</b> Ahora mismo Bitcoin está{' '}
          {state.regime_risk_on ? (
            <b className="pos">fuerte, así que tiene permiso para comprar</b>
          ) : (
            <b className="neg">débil, así que no comprará nada</b>
          )}
          . Cuando Bitcoin cae, casi todas las monedas caen con él.
        </li>
        <li>
          <b>Para vender</b> no espera a ganar una cantidad concreta: deja subir la
          moneda y la vende cuando el precio retrocede desde su punto más alto. Así
          aprovecha las subidas largas y corta las caídas pronto.
        </li>
        <li>
          <b>Nunca arriesga mucho de golpe.</b> En cada compra pone en juego como
          máximo un 1% del dinero, y si en un día llegara a perder un 2% deja de
          comprar hasta el día siguiente.
        </li>
      </ul>
    </div>
  )
}
