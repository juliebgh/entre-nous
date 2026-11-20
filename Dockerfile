FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10001 game && mkdir /data && chown game /data
COPY server.py engine.py ./
COPY public public
COPY data data
COPY migrations migrations
USER game
ENV PORT=8000 DB_PATH=/data/game.sqlite3 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["python","server.py"]
