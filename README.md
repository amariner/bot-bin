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

### Railway (paso a paso)

1. **New Project → Deploy from GitHub repo →** `amariner/bot-bin`. Railway
   detecta el `Dockerfile` de la raíz y el `railway.json` (healthcheck
   `/health`, reinicio automático).

   > El Dockerfile **no** lleva instrucción `VOLUME`: Railway la rechaza con
   > *"docker VOLUME is not supported, use Railway Volumes"* y el build falla.
   > La persistencia se configura en el paso 3.
2. **⚠️ Cambia la región a Europa ANTES de desplegar**: Settings → Deploy →
   Region → *Europe West (Amsterdam)*. Por defecto Railway despliega en
   EE. UU. y **Binance responde HTTP 451 a las IPs estadounidenses**: el bot
   arrancaría con error de universo vacío.
3. **Añade un volumen** para que las operaciones sobrevivan a cada redeploy.
   Ojo: **no está en Settings**. Se crea desde el lienzo del proyecto
   (botón `+ New` o clic derecho → *Volume*, y se elige el servicio), o desde
   la CLI, que es más directo:

   ```bash
   railway link          # elegir proyecto / entorno / servicio
   railway volume add --mount-path /data
   ```
4. **Genera el dominio**: Settings → Networking → Generate Domain.
5. Redeploy. El bot arranca solo (`BOT_AUTOSTART=1` ya viene en la imagen).

Variables opcionales (Settings → Variables): `BOT_INITIAL_CAPITAL`,
`BOT_DEFAULT_STRATEGY`, `BOT_TIMEFRAME`, `BOT_RISK_PER_TRADE`,
`BOT_DAILY_MAX_LOSS_PCT`. `BOT_AUTOSTART=0` si prefieres arrancarlo a mano.

**Aviso**: el dominio de Railway es público y sin contraseña. Con paper
trading no hay dinero en juego, pero cualquiera con la URL podría parar el
bot. Ver "Autenticación" más abajo.

### Docker en local o en un VPS

```bash
docker compose up -d --build
```

Eso compila frontend+backend, arranca el bot solo (`BOT_AUTOSTART=1`), guarda el
estado en `./botdata/` y se relanza tras reinicios del servidor.

### Autenticación

El panel no lleva login todavía. Opciones, de menos a más trabajo:

1. **Basic auth en FastAPI** con usuario/contraseña por variable de entorno.
   Es lo más rápido y sirve para Railway tal cual.
2. **Cloudflare Tunnel + Access** (gratis) si tienes un dominio en Cloudflare:
   la URL pide login con tu email/Google antes de llegar al panel y el
   websocket funciona a través del túnel. Aquí es donde Cloudflare encaja:
   como puerta de entrada, no como plataforma de ejecución (el bot es un
   proceso largo con websockets, no un Worker).
3. **Tailscale** si solo quieres acceder tú desde tus dispositivos, sin URL
   pública.

### Resistencia a caídas

El bot está pensado para levantarse solo después de cualquier golpe:

| Qué pasa | Quién lo absorbe |
|---|---|
| El proceso muere o el servidor se cae | Railway lo relanza (`ON_FAILURE`, 10 reintentos) |
| Contenedor nuevo (caída o actualización) | El estado vive en el volumen `/data`, no en la imagen |
| Se pierde todo lo que había en memoria | Al arrancar recupera de SQLite: monedas compradas, stop dinámico ya movido, dinero libre y freno diario |
| Actualización (Railway manda SIGTERM) | Guarda el estado antes de morir |
| Se cae la conexión con Binance | El websocket reconecta con espera progresiva |
| Binance devuelve 407/429/5xx | Reintentos automáticos con espera progresiva |
| Una moneda comprada sale del top-100 | Se sigue vigilando igualmente para poder venderla |

El estado se guarda como **un único JSON atómico** (nunca a medias) después de
cada operación, de cada vela y cada 30 segundos. Probado matando el proceso con
`kill -9` con posiciones abiertas: al reiniciar las recupera con sus cantidades
y sus stops exactos.

> ⚠️ **Sin volumen montado en `/data` nada de esto sirve en la nube**: el estado
> se guardaría en el disco temporal del contenedor y se borraría en cada
> actualización. Crear el volumen es el paso 3 de la guía de arriba.

**Limitación real que queda**: si el bot está caído, no puede vender. En paper
trading da igual, pero la versión con dinero real debe dejar los stops puestos
como órdenes en el propio Binance y reconciliar contra la cuenta al arrancar.

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
