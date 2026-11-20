"""Adaptation transactionnelle du stockage du jeu à PostgreSQL."""
from contextlib import closing
import hashlib
import hmac
import os
from threading import Lock

from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool


_pool = None
_pool_lock = Lock()


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            dsn = os.environ["DATABASE_URL"]
            params = conninfo_to_dict(dsn)
            tls = params.get("sslmode", "require")
            if tls not in ("require", "verify-ca", "verify-full"):
                raise RuntimeError("La base de données requiert TLS.")
            _pool = ConnectionPool(
                dsn, min_size=0, max_size=1, timeout=6, max_waiting=64,
                max_idle=60, kwargs={"prepare_threshold": None, "sslmode": tls, "connect_timeout": 5},
                open=True,
            )
        return _pool


class _Connection:
    def __init__(self):
        self.session = _get_pool().connection()
        self.conn = self.session.__enter__()

    def __enter__(self):
        self.conn.execute("SET LOCAL search_path = entre_nous_private, pg_catalog")
        return self

    def __exit__(self, typ, value, tb):
        try:
            self.session.__exit__(typ, value, tb)
        finally:
            self.session = None

    def close(self):
        if self.session is not None:
            self.session.__exit__(None, None, None)
            self.session = None

    def execute(self, sql, params=()):
        # SET LOCAL ouvre déjà la transaction. Les lectures de salon prennent
        # ensuite le verrou de ligne PostgreSQL dans server.api().
        if sql == "BEGIN IMMEDIATE":
            return
        return self.conn.execute(sql.replace("?", "%s"), params)


def connect():
    return _Connection()


def allow_entry(ip):
    secret = os.environ.get("RATE_LIMIT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("Secret de limitation manquant.")
    digest = hmac.digest(secret.encode(), ip.encode(), hashlib.sha256)
    # Une transaction indépendante comptabilise aussi les entrées refusées.
    with closing(connect()) as conn, conn:
        row = conn.execute("""
            INSERT INTO entry_limits AS limits (ip_hash, window_start, attempts)
            VALUES (?, statement_timestamp(), 1)
            ON CONFLICT (ip_hash) DO UPDATE SET
              attempts = CASE WHEN limits.window_start <= statement_timestamp() - interval '60 seconds'
                               THEN 1 ELSE least(limits.attempts + 1, 17) END,
              window_start = CASE WHEN limits.window_start <= statement_timestamp() - interval '60 seconds'
                               THEN statement_timestamp() ELSE limits.window_start END
            RETURNING attempts
        """, (digest,)).fetchone()
        return row[0] <= 16
