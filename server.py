"""Transport ASGI et transactions du jeu. L'API retourne uniquement la vue autorisée."""
import asyncio
import hashlib
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
import engine

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DB = Path(os.getenv("DB_PATH", str(ROOT / "var/game.sqlite3")))
ORIGIN = os.getenv("PUBLIC_ORIGIN", "").rstrip("/")
PG = bool(os.getenv("DATABASE_URL"))
SECURE = ORIGIN.startswith("https://")
COOKIE = "__Host-entre_nous" if SECURE else "entre_nous"
TTL = 1800
MAX_AGE = 21600
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RATE = {}
RATE_LOCK = threading.Lock()


class Problem(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def db():
    if PG:
        import pgstore
        return pgstore.connect()
    conn = sqlite3.connect(DB, timeout=5)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA secure_delete=ON")
    return conn


def expire(conn, now):
    conn.execute("DELETE FROM rooms WHERE touched<=? OR created<=?", (now - TTL, now - MAX_AGE))


def initialize():
    if PG:
        return
    os.umask(0o077)
    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(db()) as conn, conn:
        conn.executescript((ROOT / "migrations/001_rooms.sql").read_text())
        expire(conn, time.time())


def limit(ip, now):
    if PG:
        import pgstore
        if not pgstore.allow_entry(ip):
            raise Problem(429, "Trop de tentatives. Réessaie dans une minute.")
        return
    with RATE_LOCK:
        if len(RATE) > 4096:
            for key, value in list(RATE.items()):
                if value[0] <= now:
                    del RATE[key]
            if len(RATE) > 4096 and ip not in RATE:
                raise Problem(429, "Réessaie dans une minute.")
        until, count = RATE.get(ip, (0, 0))
        if until <= now:
            until, count = now + 60, 0
        if count >= 16:
            raise Problem(429, "Trop de tentatives. Réessaie dans une minute.")
        RATE[ip] = until, count + 1


def token_digest(headers):
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get("cookie", ""))
        token = cookie[COOKIE].value
    except Exception:
        token = ""
    return hashlib.sha256(token.encode()).digest()


def api(path, body, headers, ip):
    fresh = None
    if path in ("create", "join"):
        limit(ip, time.monotonic())
        fields = {"name"} if path == "create" else {"name", "code"}
        if set(body) != fields:
            raise Problem(400, "Champs inattendus ou manquants.")
        name = body["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32 or not name.isprintable():
            raise Problem(400, "Choisis un pseudonyme de 1 à 32 caractères.")
        name = name.strip()
    with closing(db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        now = time.time()
        if path == "create":
            while True:
                code = "".join(secrets.choice(ALPHABET) for _ in range(7))
                if not conn.execute("SELECT 1 FROM rooms WHERE code=?", (code,)).fetchone():
                    break
            room = engine.new(name, now)
            seat = 0
            conn.execute("INSERT INTO rooms VALUES(?,?,?,?)", (code, now, now, "{}"))
        elif path == "join":
            raw = body["code"]
            if not isinstance(raw, str) or not re.fullmatch("[A-Za-z2-9]{7}", raw):
                raise Problem(400, "Vérifie le code du salon.")
            code = raw.upper()
            row = conn.execute("SELECT state FROM rooms WHERE code=? AND touched>? AND created>?" + (" FOR UPDATE OF rooms" if PG else ""),
                               (code, now-TTL, now-MAX_AGE)).fetchone()
            now = time.time()
            if not row:
                raise Problem(404, "Salon introuvable ou expiré.")
            if conn.execute("SELECT 1 FROM seats WHERE room=? AND (seat=1 OR token_hash=?)",
                            (code, token_digest(headers))).fetchone():
                raise Problem(409, "Ce salon est déjà occupé.")
            room = json.loads(row[0])
            seat = 1
            engine.join(room, name, now)
        else:
            row = conn.execute("""SELECT r.code,s.seat,r.state FROM seats s JOIN rooms r ON r.code=s.room
                WHERE s.token_hash=? AND r.touched>? AND r.created>?""" + (" FOR UPDATE OF r" if PG else ""),
                               (token_digest(headers), now-TTL, now-MAX_AGE)).fetchone()
            if not row:
                raise Problem(401, "Session absente ou expirée.")
            now = time.time()
            code, seat, stored = row
            room = json.loads(stored)
            engine.tick(room, now)
            if path == "act":
                engine.act(room, seat, body, now)
        if path in ("create", "join"):
            fresh = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO seats VALUES(?,?,?,?)", (hashlib.sha256(fresh.encode()).digest(), code, seat, now))
        else:
            conn.execute("UPDATE seats SET seen=? WHERE room=? AND seat=?", (now, code, seat))
        state = json.dumps(room, separators=(",", ":"), ensure_ascii=False)
        if path == "state" and state == stored:
            conn.execute("UPDATE rooms SET touched=? WHERE code=?", (now, code))
        else:
            conn.execute("UPDATE rooms SET state=?, touched=? WHERE code=?", (state, now, code))
        result = engine.view(room, seat, now)
        result.update(code=code, serverNow=now, online=[now-s[0] < 8 for s in
                      conn.execute("SELECT seen FROM seats WHERE room=? ORDER BY seat", (code,))])
        return result, fresh


async def sweep():
    while True:
        await asyncio.sleep(30)
        def clean():
            with closing(db()) as conn, conn:
                expire(conn, time.time())
        await asyncio.to_thread(clean)


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        await receive()
        initialize()
        task = None if PG else asyncio.create_task(sweep())
        await send({"type":"lifespan.startup.complete"})
        await receive()
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await send({"type":"lifespan.shutdown.complete"})
        return
    path = scope["path"]
    method = scope["method"]
    headers = {k.decode():v.decode("latin1") for k,v in scope["headers"]}
    extra = []
    status, mime = 200, "application/json; charset=utf-8"
    try:
        if path.startswith("/api/"):
            action = path[5:]
            if action not in ("state","create","join","act"):
                raise Problem(404, "Route inconnue.")
            if method != ("GET" if action == "state" else "POST"):
                raise Problem(405, "Méthode refusée.")
            body = {}
            if method == "POST":
                origin = headers.get("origin")
                expected = ORIGIN or scope["scheme"] + "://" + headers.get("host", "")
                if (origin and origin != expected) or headers.get("sec-fetch-site") == "cross-site":
                    raise Problem(403, "Origine refusée.")
                if headers.get("content-type","").split(";")[0].strip() != "application/json":
                    raise Problem(415, "JSON requis.")
                raw = bytearray()
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    raw.extend(event.get("body", b""))
                    if len(raw) > 4096:
                        raise Problem(413, "Requête trop longue.")
                    if not event.get("more_body"):
                        break
                try:
                    body = json.loads(raw)
                except (ValueError, RecursionError):
                    raise Problem(400, "JSON invalide.")
                if type(body) != dict:
                    raise Problem(400, "Objet attendu.")
            result, token = await asyncio.to_thread(api, action, body, headers, scope["client"][0])
            if token:
                attributes = "; Path=/; HttpOnly; SameSite=Strict; Max-Age=21600"
                extra.append((b"set-cookie", (COOKIE+"="+token+attributes+("; Secure" if SECURE else "")).encode()))
            data = json.dumps(result, ensure_ascii=False).encode()
        else:
            if method != "GET":
                raise Problem(405, "Méthode refusée.")
            asset = (PUBLIC / (path.lstrip("/") or "index.html")).resolve()
            if not asset.is_relative_to(PUBLIC) or not asset.is_file():
                raise Problem(404, "Page introuvable.")
            mime = mimetypes.guess_type(asset)[0] or "application/octet-stream"
            data = asset.read_bytes()
    except (Problem, ValueError) as err:
        status = err.status if isinstance(err, Problem) else 400
        data = json.dumps({"error":str(err)}).encode()
    except Exception:
        status, data = 500, b'{"error":"Service temporairement indisponible."}'
    extra.extend([(b"content-type",mime.encode()),(b"cache-control",b"no-store"),
                  (b"x-content-type-options",b"nosniff"),(b"referrer-policy",b"no-referrer"),
                  (b"permissions-policy",b"camera=(), microphone=(), geolocation=()"),
                  (b"content-security-policy",b"default-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")])
    await send({"type":"http.response.start","status":status,"headers":extra})
    await send({"type":"http.response.body","body":data})


if __name__ == "__main__":
    if ORIGIN and (urlsplit(ORIGIN).scheme not in ("http","https") or not urlsplit(ORIGIN).netloc):
        raise SystemExit("PUBLIC_ORIGIN doit être une origine HTTP(S).")
    uvicorn.run(app, host=os.getenv("HOST","0.0.0.0"), port=int(os.getenv("PORT","8000")),
                access_log=False, server_header=False, ws="none", limit_concurrency=150,
                forwarded_allow_ips=os.getenv("TRUSTED_PROXY",""), timeout_keep_alive=5)
