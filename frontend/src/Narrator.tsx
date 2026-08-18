import { useEffect, useState } from 'react'
import type { BotState } from './types'

/**
 * Explica en castellano llano qué es el bot y qué está haciendo ahora mismo.
 * Va plegado: en una línea se ve la situación, y el icono ⓘ despliega la
 * explicación completa. La preferencia se recuerda entre visitas.
 */

const CLAVE = 'bot-bin.explicacion-abierta'

function faltaPara(ts: number | undefined): string {
  if (!ts) return 'poco'
  const min = Math.max(0, Math.round((ts - Date.now()) / 60000))
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h}h ${m}min` : `${h} horas`
}

/** Una sola frase con la situación: lo que se ve sin desplegar nada. */
function resumen(state: BotState): string {
  if (state.status === 'stopped') return 'El bot está parado: no vigila ni compra nada.'
  if (state.status === 'warming_up') return 'Preparándose: descargando el histórico de las monedas.'
  if (state.status === 'error') return `Error al arrancar: ${state.error}`
  if (state.circuit_breaker)
    return 'Freno de seguridad activado: hoy no comprará más (ha perdido el 2% del día).'

  const pos = state.open_positions.length
  const tiene = pos === 0
    ? 'sin ninguna moneda comprada'
    : `con ${pos} moneda${pos > 1 ? 's' : ''} comprada${pos > 1 ? 's' : ''}`
  return `Vigilando ${state.universe_size} monedas, ${tiene}. ` +
    `Próxima revisión en ${faltaPara(state.next_close_ts)}.`
}

export function Narrator({ state, connected }: { state: BotState | null; connected: boolean }) {
  const [abierto, setAbierto] = useState(() => localStorage.getItem(CLAVE) === '1')
  useEffect(() => { localStorage.setItem(CLAVE, abierto ? '1' : '0') }, [abierto])

  if (!connected)
    return (
      <div className="narrator warn">
        <div className="narrator-linea">
          <span className="narrator-icono">⚠️</span>
          <span><b>Sin conexión con el bot.</b> La página no recibe datos. Si acabas de
          desplegar una versión nueva, espera unos segundos y recarga.</span>
        </div>
      </div>
    )
  if (!state) return null

  const grave = state.status === 'error' || state.circuit_breaker
  const cada = state.timeframe === '4h' ? '4 horas' : state.timeframe

  return (
    <div className={`narrator ${grave ? 'bad' : ''} ${abierto ? 'abierto' : ''}`}>
      <button className="narrator-linea" onClick={() => setAbierto(!abierto)}
              aria-expanded={abierto} title="Ver la explicación completa">
        <span className="narrator-icono" aria-hidden="true">ⓘ</span>
        <span className="narrator-resumen">{resumen(state)}</span>
        <span className="narrator-caret">{abierto ? '▾' : '▸'}</span>
      </button>

      {abierto && (
        <div className="narrator-detalle">
          <h4>Qué es esto</h4>
          <p>
            Un bot que compra y vende criptomonedas solo, en Binance, <b>con dinero
            simulado</b>. Los precios son reales; las compras no. Sirve para comprobar si
            la estrategia funciona antes de arriesgar dinero de verdad.
          </p>

          <h4>Qué está haciendo ahora</h4>
          <ul>
            <li>Vigila las <b>{state.universe_size} monedas</b> con más movimiento de Binance.</li>
            <li>
              Tiene <b>{state.open_positions.length} de {state.max_positions}</b> monedas
              compradas. Lleva <b>{state.candles_processed}</b> revisiones hechas y ha visto{' '}
              <b>{state.signals_seen}</b> oportunidades, de las que descartó{' '}
              <b>{state.signals_rejected}</b>.
            </li>
            <li>
              Bitcoin está{' '}
              {state.regime_risk_on
                ? <b className="pos">fuerte, así que tiene permiso para comprar</b>
                : <b className="neg">débil, así que no comprará nada</b>}.
            </li>
            {state.near_signals.length > 0 && (
              <li>Hay <b>{state.near_signals.length}</b> monedas cerca de cumplir sus
              condiciones (abajo, en «A punto de comprar»).</li>
            )}
          </ul>

          <h4>Cuándo compra</h4>
          <p>
            Cada {cada} revisa todas las monedas. Compra una solo si se cumplen las
            <b> tres</b> cosas a la vez:
          </p>
          <ol>
            <li>Supera su precio máximo de los últimos <b>3 días</b>.</li>
            <li>Se negocia <b>4 veces más</b> de lo habitual (es lo que casi siempre falla).</li>
            <li>Bitcoin está por encima de su media, porque si BTC cae, cae casi todo.</li>
          </ol>

          <h4>Cuándo vende</h4>
          <p>
            No pone un objetivo de ganancia. Deja subir la moneda y va subiendo con ella un
            <b> precio de venta automática</b> que nunca baja. Vende cuando el precio
            retrocede hasta ese nivel. Así aguanta las subidas largas y corta pronto las caídas.
          </p>

          <h4>Cuánto puede perder</h4>
          <p>
            En cada compra arriesga como máximo el <b>1%</b> del dinero. Nunca tiene más de{' '}
            <b>{state.max_positions}</b> monedas a la vez. Y si en un día pierde un <b>2%</b>,
            deja de comprar hasta el día siguiente.
          </p>

          <h4>Qué esperar</h4>
          <p>
            Opera <b>poco y de forma selectiva</b>: verás días enteros sin ninguna compra, y
            eso es lo correcto. En las pruebas históricas acompañaba al mercado cuando subía y
            perdía bastante menos cuando bajaba. <b>No gana todos los días</b>, y quien
            prometa eso miente.
          </p>
        </div>
      )}
    </div>
  )
}
