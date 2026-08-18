# bot-bin — contexto para Claude

Bot de **paper trading** (spot, solo largos, sin apalancamiento) sobre los 100
pares USDT con más volumen de Binance, con dashboard en tiempo real. **No envía
órdenes reales**: precios reales por websocket, fills simulados con comisión y
slippage.

## Cómo arrancar

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000   # API + frontend en :8000
cd frontend && npm run dev                                  # solo desarrollo de UI
cd backend && .venv/bin/python -m pytest tests/ -q          # 45 tests
```
Tras tocar el frontend: `cd frontend && npm run build`.

## LA CONFIGURACIÓN GANADORA

`momentum_4h` (preset por defecto), en **velas de 4h**:

| Parámetro | Valor | Por qué |
|---|---|---|
| lookback | 20 | rotura del máximo de 20 velas |
| vol_mult | 4.0 | solo roturas con 4× el volumen medio — operar poco y bien |
| atr_stop | 2.0 | stop inicial a 2·ATR |
| trail_atr | 3.0 | stop dinámico (chandelier); sin take-profit fijo |
| max_bars | 0 | sin stop temporal: el trailing decide la salida |
| filtro BTC | sí | solo abre con BTC sobre su EMA(50) |

**Resultado en las 4 pruebas de validación (comisión 0,075% con BNB):**

| Prueba | Periodo / datos | Mercado | Bot | PF | maxDD |
|---|---|---|---|---|---|
| TRAIN | dic 25 → abr 26 | −20,2% | **+0,5%** | – | – |
| SELECT | abr → jun 26 | +6,7% | **+22,0%** | 1,96 | 8,2% |
| HOLDOUT temporal | jun → ago 26 | +19,0% | **+9,7%** | 1,52 | 7,7% |
| Símbolos nunca usados (41-80) | dic → ago 26 | −31,3% | **+3,9%** | 1,04 | 25,1% |

**Positiva en las cuatro**, con el mercado oscilando entre −31% y +19%.

### Carácter de la estrategia (scripts/diagnose.py, 16 ventanas mensuales)

- Ventanas ALCISTAS: mercado +7,7% / bot +7,0% (ajustadas) · +4,8% / +3,3% (nuevas)
  → **acompaña al mercado**, con un rezago de ~1 punto.
- Ventanas BAJISTAS: mercado −8,0% / bot −3,0% · −11,9% / **+0,3%**
  → **protege mucho**: entre +5 y +12 puntos mejor que el mercado.

Es un perfil asimétrico: subida parecida al mercado, caída mucho menor. **No** es
una máquina de ganar todos los días.

### Robustez (scripts/sensitivity.py)

Meseta parcial: **15 de 22 variantes de parámetros siguen en positivo** sobre
símbolos nunca usados. Sensible sobre todo a `trail_atr` (>3.0 lo rompe) y a
`lookback` (30 lo rompe). Hay señal, pero no es un óptimo ancho: no tocar
parámetros sin repetir el proceso completo.

## Método de validación (no saltárselo)

```bash
.venv/bin/python scripts/experiment.py --symbols 40 --days 240 --timeframe 4h \
    --grid entries --out experiment_4h.json      # FASE 1+2: train + select
.venv/bin/python scripts/holdout.py --timeframe 4h --experiment experiment_4h.json \
    --out holdout_4h.json                        # FASE 3: test final, UNA vez
.venv/bin/python scripts/sensitivity.py --timeframe 4h   # ¿meseta o pico de suerte?
.venv/bin/python scripts/diagnose.py --preset momentum_4h --timeframe 4h  # carácter
```

Reglas: la rejilla se explora en TRAIN; lo que gana se reprueba en SELECT; solo
lo que gana en ambos toca el HOLDOUT, y el HOLDOUT se usa **una sola vez**.
Todo se compara contra comprar y mantener. El test de símbolos 41-80 es el más
duro: son monedas que nunca intervinieron en ningún ajuste.

## Validación de vecinos (2026-08-18, juez: monedas 81-120, jamás usadas)

`scripts/validate_neighbors.py`. Resultado:
- **trailing 2.0: REFUTADO** (−20,5% vs −17,1% de la actual; el patrón
  "más ceñido = mejor" no se repitió). Era ruido de las monedas 41-80.
- **EMA200: REFUTADA en el test decisivo** (`scripts/decide_ema200.py`,
  periodo virgen 25 abr → 21 dic 2025, jamás usado antes): pierde contra la
  base en los 3 grupos de monedas (criterio exigía ganar en ≥2). Sus dos
  victorias previas eran un artefacto del tramo dic25-ago26, no una propiedad
  de la estrategia — ambos "jueces" compartían periodo temporal. Lección: dos
  conjuntos de símbolos del MISMO periodo no son evidencia independiente.
  Detalle en `data/decide_ema200.json`. En ese periodo virgen la base batió
  al mercado en los 3 grupos (+4,5 / +55,7 / +38,2 puntos vs B&H).

**CONCLUSIÓN DEFINITIVA DEL PROCESO: `momentum_4h` sin filtro de tendencia
propio es la mejor configuración encontrada. La búsqueda por backtesting está
agotada; lo único que queda es paper trading prolongado.**

## Hipótesis ya probadas y REFUTADAS (no repetirlas)

- **Timeframes cortos (5m, 15m)**: las comisiones se comen todo. 5m: −29%.
- **Take-profit fijo sin trailing**: peor en todos los periodos.
- **Salidas por EMA (outEMA20/50/100)**: ganan en TRAIN, se hunden en SELECT
  (−13% a −30%). Refutado.
- **Trailing ancho (5, 6, 8·ATR)**: igual, se hunde en SELECT.
- **1h con filtro de tendencia propia (EMA100)**: gana en bajista pero pierde
  −19% en el holdout alcista. Descartada en favor de 4h.
- **Filtros de volatilidad (ATR mín/máx) y margen de rotura**: neutros o peores.
- **Mean reversion (RSI)**: casi no opera o pierde. Sin ventaja.

## Decisiones de arquitectura

- Universo = top-100 pares USDT por volumen 24h (no market cap); `app/universe.py`.
- Validación = paper trading sobre datos reales, NO el Spot Testnet (libros vacíos).
- Riesgo: 1% del equity por trade, máx 5 posiciones, cap 20% por posición,
  **circuit breaker −2% diario**.
- `engine/core.py` es el ÚNICO motor: backtest y vivo comparten lógica.
- El trailing se mueve DESPUÉS de comprobar salidas, para que el stop de la vela
  N sea el fijado al cierre de N−1 (sin sesgo intrabar). Blindado en
  `tests/test_trailing.py`.
- Websocket por el puerto **443** (el 9443 está bloqueado aquí).
- `trust_env=False` en httpx: el proxy de sistema del Mac corporativo devuelve
  **407**. `BOT_TRUST_ENV_PROXY=1` lo reactiva.
- Python 3.9: `Optional[...]`, nunca `X | None` en anotaciones runtime.

## Resistencia a caídas ("que se levante solo")

Capas, de fuera hacia dentro. Ninguna sustituye a las otras:

| Patada | Qué la absorbe |
|---|---|
| Proceso muere / servidor cae | Railway `restartPolicyType: ALWAYS` levanta otro contenedor |
| Contenedor nuevo (caída o actualización) | El estado vive en `/data` (volumen), no en la imagen |
| Estado en memoria perdido | `TradingEngine.to_state()/restore_state()` en SQLite (`kv['engine_state']`) |
| Actualización con SIGTERM | `@app.on_event("shutdown")` guarda antes de morir |
| Websocket de Binance cae | `MarketStream` reconecta con backoff exponencial |
| Binance devuelve 407/429/5xx | `BinancePublic._get` reintenta con backoff |
| Moneda comprada sale del top-100 | `start()` la añade igualmente al stream y al warmup |

Detalles que importan:
- El estado se guarda como **un único JSON atómico**, nunca campo a campo: una
  caída a mitad de escritura no puede dejar medio estado.
- Se guarda tras cada evento, tras cada vela (el trailing se mueve ahí) y cada
  30 s como red de seguridad.
- **El freno diario se restaura activado**: reiniciar no puede usarse para
  saltarse el límite de pérdidas del día.
- `POST /api/bot/reset` (solo con el bot parado) borra el estado y vuelve al
  capital inicial.
- Estados de versión distinta se ignoran (`STATE_VERSION`): mejor arranque
  limpio que estado corrupto.

**Lo que todavía NO cubre**: en real, si el bot está caído no puede vender. Por
eso la versión con dinero real debe colocar los stops como órdenes
`STOP_LOSS_LIMIT` en el propio Binance y reconciliar contra la cuenta al
arrancar (ver "Próximos pasos").

## Panel y despliegue

- La UI muestra: feed de actividad (eventos `open`/`close`/`signal_skipped` con
  texto en español, persistidos en SQLite con su `text`), radar de "cerca de dar
  señal" (distancia a rotura + ratio de volumen), posiciones con máximo/stop/
  colchón, historial persistente de operaciones (`/api/trades`, `/api/events`).
- `Dockerfile` + `docker-compose.yml` en la raíz; `BOT_AUTOSTART=1` arranca el
  bot al levantar el proceso. Estado en volumen `/data`.
- Cloudflare Workers NO sirve para ejecutar el bot (proceso largo + websockets);
  Cloudflare solo como puerta: Tunnel + Access para autenticación, o Tailscale.
- Hosting recomendado: VPS UE o Fly.io región UE (Binance bloquea IPs de EE. UU.).

## Próximos pasos

1. **Paper trading prolongado** con `momentum_4h`: es la única prueba que queda.
   Con velas de 4h espera del orden de 20-40 operaciones al mes.
2. Simular órdenes límite reales (llenado solo si el precio vuelve al nivel)
   para saber si el escenario maker (0,02%) es alcanzable.
3. Si se quiere reducir el drawdown del 25% en símbolos nuevos: probar
   `trail_atr` 2.0-2.5, pero **validándolo desde cero**, no sobre los datos ya
   usados aquí.
4. Refresco periódico del universo en vivo (ahora se fija al arrancar).
5. Reconstruir posiciones abiertas desde SQLite al reiniciar el proceso.
