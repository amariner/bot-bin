# bot-bin — Bot de paper trading sobre Binance

Bot de trading cortoplacista sobre los **100 pares USDT con más volumen de Binance**,
con **paper trading sobre datos reales** (precios en vivo por websocket, órdenes
simuladas con comisiones y slippage) y un **dashboard en tiempo real**.

> ⚠️ Modo actual: **simulación**. No se envía ninguna orden real. La conexión al
> Spot Testnet existe solo como smoke test de integración.

## Arquitectura

```
backend/  Python 3.9 + FastAPI
  app/
    config.py        Parámetros (capital, riesgo, universo, comisiones) vía env BOT_*
    universe.py      Top-100 pares USDT por volumen 24h (sin stables ni apalancados)
    binance_client.py REST público + órdenes firmadas en testnet
    streams.py       Websocket de velas + miniTicker con reconexión
    indicators.py    SMA/EMA/RSI/ATR puros
    strategy/        momentum (breakout+volumen) y meanrev (RSI+EMA200)
    engine/
      core.py        Motor de ejecución ÚNICO para backtest y vivo
      paper.py       Simulador de fills (slippage + comisiones)
      risk.py        Sizing por riesgo fijo + circuit breaker diario
    backtest/        Descarga/caché de históricos + runner multi-símbolo
    trader.py        Orquestador en vivo (warmup, stream, persistencia, broadcast)
    main.py          API REST + websocket /ws para la UI
  scripts/
    run_backtest.py  Backtest comparativo de estrategias
    testnet_smoke.py Prueba de órdenes en Spot Testnet (necesita claves)
  tests/             31 tests unitarios (motor, riesgo, indicadores, estrategias)
frontend/  React + Vite + TypeScript + lightweight-charts
```

## Gestión de riesgo (lo importante)

- **1% del equity en riesgo por operación** (el tamaño se calcula desde la distancia al stop).
- Máximo **5 posiciones simultáneas**, máximo 20% del equity por posición.
- **Circuit breaker: −2% de pérdida diaria ⇒ el bot deja de abrir posiciones hasta el día siguiente (UTC)**.
- Solo spot, solo largos, sin apalancamiento.
- Comisión simulada 0.1% por lado + slippage 5 pbs (peor que la realidad con BNB, a propósito).

## Estrategias

| Nombre | Idea | Entrada | Salida |
|---|---|---|---|
| `momentum_4h` ⭐ | Las roturas con mucho volumen continúan | Cierre > máximo 20 velas + volumen >4× media + BTC sobre su EMA50 | Stop 2·ATR que pasa a dinámico a 3·ATR del máximo |
| `momentum` | Versión original, menos selectiva | Volumen >2,5× media | Stop 2·ATR, TP 3·ATR, tiempo 48 velas |
| `meanrev` | Comprar caídas en tendencia alcista | RSI(14)<28 con precio > EMA200 | Stop 2·ATR, TP 2·ATR, RSI>55 |

Solo `momentum_4h` ha superado el proceso de validación completo.

## Configuración validada: `momentum_4h`

Tras probar más de 130 configuraciones en 4 timeframes con un proceso de tres
fases (búsqueda → selección → test final de un solo uso), la ganadora es una
rotura de máximos muy selectiva con stop dinámico, en **velas de 4 horas**.

| Prueba | Mercado | Bot |
|---|---|---|
| Búsqueda (dic 25 → abr 26) | −20,2% | +0,5% |
| Selección (abr → jun 26) | +6,7% | +22,0% |
| **Test final, periodo nuevo** (jun → ago 26) | +19,0% | **+9,7%** |
| **Test final, 31 monedas nunca usadas** | −31,3% | **+3,9%** |

Es **positiva en las cuatro**, con el mercado moviéndose entre −31% y +19%. Su
carácter es asimétrico: en subidas acompaña al mercado (rezago de ~1 punto) y en
caídas protege mucho (entre 5 y 12 puntos mejor). **No** gana todos los días.

Detalle del método, hipótesis refutadas y límites en [CLAUDE.md](CLAUDE.md).
La pestaña "Búsqueda de estrategia" del dashboard muestra todo el proceso.

## Uso

```bash
# 1. Backend (puerto 8000)
cd backend && .venv/bin/uvicorn app.main:app --port 8000

# 2. Frontend en desarrollo (puerto 5173, proxy al backend)
cd frontend && npm run dev

# Backtest comparativo (descarga y cachea los datos en backend/data/)
cd backend && .venv/bin/python scripts/run_backtest.py --symbols 20 --days 30

# Tests
cd backend && .venv/bin/python -m pytest tests/ -q
```

En la UI: elegir estrategia y pulsar **Start**. El bot selecciona el universo,
precalienta 300 velas por símbolo y empieza a procesar el mercado en vivo.

## Dejarlo funcionando 24/7 (despliegue)

El bot es un proceso Python de larga duración con websockets abiertos: **no
encaja en Cloudflare Workers/Pages** (pensados para funciones cortas en JS).
Dónde sí encaja:

| Opción | Coste | Notas |
|---|---|---|
| **VPS europeo (Hetzner, DigitalOcean…)** ⭐ | ~4-6 €/mes | Docker + `restart: unless-stopped`. Elegir región UE: Binance bloquea IPs de EE. UU. |
| Fly.io / Railway (contenedor always-on) | ~5 $/mes | Fácil de desplegar, elegir región UE |
| Mac/miniPC en casa encendido | 0 € | Con Docker o launchd; acceso remoto vía Cloudflare Tunnel |

Con Docker (ya incluido en el repo):

```bash
docker compose up -d --build
```

Eso compila frontend+backend, arranca el bot solo (`BOT_AUTOSTART=1`), guarda el
estado en `./botdata/` y se relanza tras reinicios del servidor.

**Autenticación**: no expongas el puerto 8000 a internet tal cual. Lo más simple
y sólido es ponerlo detrás de **Cloudflare Tunnel + Cloudflare Access** (gratis:
la URL pública pide login con tu email/Google antes de llegar al panel, y el
websocket funciona a través del túnel) o usar **Tailscale** si solo quieres
acceder tú desde tus dispositivos sin URL pública. Ahí es donde Cloudflare sí
encaja: como puerta de entrada, no como plataforma de ejecución.

**Limitación conocida**: si el proceso se reinicia con posiciones abiertas, esas
posiciones no se recuperan (el historial de operaciones cerradas sí). Está en la
lista de próximos pasos.

## Testnet (opcional)

Crear claves gratis en <https://testnet.binance.vision> (login con GitHub) y:

```bash
export BINANCE_TESTNET_API_KEY=...
export BINANCE_TESTNET_API_SECRET=...
cd backend && .venv/bin/python scripts/testnet_smoke.py --order
```

## Qué NO promete esto

Ninguna estrategia garantiza acabar el día/semana/mes en positivo. El objetivo
del proyecto es **medir con rigor** (backtest → paper trading → métricas) si una
estrategia tiene ventaja tras comisiones, y limitar las pérdidas cuando no la
tiene. No pasar a dinero real sin varias semanas de paper trading consistente.
