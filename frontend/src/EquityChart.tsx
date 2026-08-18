import { useEffect, useRef } from 'react'
import { createChart, LineSeries, type IChartApi, type ISeriesApi } from 'lightweight-charts'

interface Props {
  history: { ts: number; equity: number }[]
  live?: { ts: number; equity: number } | null
  baseline?: number
  height?: number
}

/**
 * Curva de equity. Fuerza un rango mínimo de ±0.5% alrededor de la línea base
 * para que una curva plana (sin operaciones aún) no se dibuje con una escala
 * absurda de 4 decimales.
 */
export function EquityChart({ history, live, baseline, height = 280 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const lastTsRef = useRef(0)
  const baselineRef = useRef(baseline)
  baselineRef.current = baseline
  // React limpia los efectos en orden de declaración: el del gráfico va primero
  // y llama a chart.remove(), dejando la serie destruida. Sin esta marca, los
  // efectos posteriores operan sobre objetos muertos y lanzan "Object is disposed".
  const disposedRef = useRef(false)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#8b93a7', fontSize: 11 },
      grid: {
        vertLines: { color: 'rgba(139,147,167,0.07)' },
        horzLines: { color: 'rgba(139,147,167,0.07)' },
      },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: 'rgba(139,147,167,0.2)' },
      rightPriceScale: { borderColor: 'rgba(139,147,167,0.2)' },
      crosshair: { mode: 0 },
    })
    const series = chart.addSeries(LineSeries, {
      color: '#4f8ef7',
      lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      autoscaleInfoProvider: (original: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
        const res = original()
        const base = baselineRef.current
        if (!res || !base) return res
        const margin = base * 0.005 // al menos ±0.5% visible
        return {
          ...res,
          priceRange: {
            minValue: Math.min(res.priceRange.minValue, base - margin),
            maxValue: Math.max(res.priceRange.maxValue, base + margin),
          },
        }
      },
    })
    chartRef.current = chart
    seriesRef.current = series
    disposedRef.current = false
    return () => {
      disposedRef.current = true
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  // Línea horizontal punteada en el capital inicial
  useEffect(() => {
    const series = seriesRef.current
    if (!series || !baseline || disposedRef.current) return
    const line = series.createPriceLine({
      price: baseline,
      color: 'rgba(139,147,167,0.5)',
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: 'inicial',
    })
    return () => {
      if (disposedRef.current) return   // el gráfico ya se destruyó entero
      series.removePriceLine(line)
    }
  }, [baseline])

  useEffect(() => {
    if (!seriesRef.current || disposedRef.current) return
    if (history.length === 0) {
      seriesRef.current.setData([])
      lastTsRef.current = 0
      return
    }
    // lightweight-charts exige tiempos estrictamente crecientes y únicos
    const seen = new Set<number>()
    const data = history
      .map((p) => ({ time: Math.floor(p.ts / 1000), value: p.equity }))
      .filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)))
      .sort((a, b) => a.time - b.time)
    seriesRef.current.setData(data as never)
    lastTsRef.current = data[data.length - 1].time * 1000
    chartRef.current?.timeScale().fitContent()
  }, [history])

  useEffect(() => {
    if (!seriesRef.current || !live || disposedRef.current) return
    const t = Math.floor(live.ts / 1000)
    if (t * 1000 <= lastTsRef.current) return
    seriesRef.current.update({ time: t, value: live.equity } as never)
    lastTsRef.current = t * 1000
  }, [live])

  return <div ref={containerRef} style={{ height }} />
}
