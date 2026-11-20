CREATE TABLE IF NOT EXISTS rooms (
 code TEXT PRIMARY KEY,
 created REAL NOT NULL,
 touched REAL NOT NULL,
 state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seats (
 token_hash BLOB PRIMARY KEY,
 room TEXT NOT NULL REFERENCES rooms(code) ON DELETE CASCADE,
 seat INTEGER NOT NULL CHECK (seat IN (0,1)),
 seen REAL NOT NULL,
 UNIQUE(room,seat)
);
CREATE INDEX IF NOT EXISTS rooms_expiry ON rooms(touched);
PRAGMA user_version=1;
