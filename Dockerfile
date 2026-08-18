# Imagen única: compila el frontend y sirve todo desde FastAPI en :8000
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/validation ./validation
# main.py busca el build en ../frontend/dist relativo a backend/
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Estado (SQLite + caché de históricos) fuera de la imagen, en un volumen
ENV BOT_DB_PATH=/data/bot.db \
    BOT_DATA_DIR=/data \
    BOT_AUTOSTART=1
VOLUME /data
EXPOSE 8000

# Railway (y otros PaaS) inyectan el puerto en $PORT; en local cae a 8000.
# Forma shell para que la variable se expanda.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
