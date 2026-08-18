"""API FastAPI: control del bot, estado para la UI y websocket en tiempo real."""
import asyncio
import json
import logging
import os
import time
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analysis import analyse
from .config import settings
from .db import Database
from .strategy import STRATEGIES, describe_strategies
from .trader import LiveTrader

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="bot-bin", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

db = Database()
trader = LiveTrader(db)


@app.on_event("startup")
async def _maybe_autostart():
    if settings.autostart:
        logging.getLogger("main").info("BOT_AUTOSTART=1: arrancando el bot")
        asyncio.create_task(trader.start())


@app.on_event("shutdown")
async def _save_on_shutdown():
    """Railway manda SIGTERM en cada actualización; guardamos antes de morir
    para que el contenedor nuevo continúe justo donde lo dejó el viejo."""
    logging.getLogger("main").info("apagando: guardando estado")
    trader._save_state()


class StartRequest(BaseModel):
    strategy: Optional[str] = None
    capital: Optional[float] = None


@app.get("/health")
async def health():
    """Sonda ligera para el healthcheck del PaaS: no toca el motor ni la BD."""
    return {"ok": True, "bot": trader.status}


@app.get("/api/status")
async def status():
    return trader.state_snapshot()


@app.get("/api/strategies")
async def strategies():
    return {"available": list(STRATEGIES), "default": settings.default_strategy,
            "details": describe_strategies()}


@app.get("/api/trades")
async def trades(limit: int = 100):
    return db.recent_trades(limit)


@app.get("/api/events")
async def events(limit: int = 100, type: Optional[str] = None):
    """Registro persistente de actividad (compras, ventas, señales descartadas)."""
    rows = db.recent_events(min(limit, 1000))
    if type:
        wanted = set(type.split(","))
        rows = [r for r in rows if r["type"] in wanted]
    return rows


@app.get("/api/analysis")
async def analysis(hours: int = 0):
    """Registro agregado en conclusiones. Pensado tanto para la pestaña
    'Análisis' de la interfaz como para consultarlo en remoto y decidir
    mejoras con datos en vez de con intuiciones."""
    since = int(time.time() * 1000) - hours * 3_600_000 if hours else 0
    return analyse(
        events=db.recent_events(2000),
        trades=db.recent_trades(1000),
        equity=db.equity_history(since_ts=since, limit=5000),
        state=trader.state_snapshot(),
        since_ts=since,
    )


@app.get("/api/equity")
async def equity(since: int = 0):
    return db.equity_history(since_ts=since)


@app.get("/api/universe")
async def universe():
    return trader.universe


def _load_json(filename: str) -> dict:
    """Lee un resultado de validación. Prioriza backend/validation (versionado,
    presente en la imagen Docker) y cae a data/ si se acaba de regenerar."""
    path = os.path.join(settings.validation_dir, filename)
    if not os.path.exists(path):
        path = os.path.join(settings.data_dir, filename)
    if not os.path.exists(path):
        return {"available": False}
    with open(path) as f:
        data = json.load(f)
    data["available"] = True
    return data


@app.get("/api/walkforward")
async def walkforward():
    """Validación fuera de muestra inicial (scripts/walkforward.py)."""
    return _load_json("walkforward.json")


@app.get("/api/experiment")
async def experiment():
    """Búsqueda en rejilla sobre TRAIN + SELECT (scripts/experiment.py)."""
    return _load_json(settings.validation_experiment_file)


@app.get("/api/holdout")
async def holdout():
    """Test final: periodo y símbolos nunca usados (scripts/holdout.py)."""
    return _load_json(settings.validation_holdout_file)


@app.post("/api/bot/start")
async def bot_start(req: StartRequest):
    global trader
    if trader.status in ("running", "warming_up"):
        return {"ok": False, "error": "el bot ya está en marcha"}
    if req.strategy or req.capital:
        trader = LiveTrader(db, strategy_name=req.strategy, capital=req.capital)
    asyncio.create_task(trader.start())
    return {"ok": True}


@app.post("/api/bot/stop")
async def bot_stop(liquidate: bool = False):
    await trader.stop(liquidate=liquidate)
    return {"ok": True}


@app.post("/api/bot/reset")
async def bot_reset():
    """Empieza de cero: olvida posiciones y vuelve al capital inicial.
    Solo con el bot parado, para no borrar dinero que está invertido."""
    global trader
    if trader.status in ("running", "warming_up"):
        return {"ok": False, "error": "para el bot antes de reiniciar el estado"}
    db.set_kv(LiveTrader.STATE_KEY, {})
    trader = LiveTrader(db)
    return {"ok": True, "message": "estado borrado; el bot arrancará limpio"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = trader.subscribe()
    try:
        await ws.send_json(trader.state_snapshot())
        while True:
            try:
                state = await asyncio.wait_for(q.get(), timeout=5.0)
            except asyncio.TimeoutError:
                state = trader.state_snapshot()   # heartbeat con estado fresco
            await ws.send_json(state)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        trader.unsubscribe(q)


# En producción servimos el build del frontend desde el propio backend
_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
