-- Exécuter une fois, dans un projet Supabase dédié, comme administrateur.
-- Un nom déjà utilisé interrompt et annule intégralement cette installation.
BEGIN;
CREATE ROLE entre_nous_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE SCHEMA entre_nous_private;
REVOKE ALL ON SCHEMA entre_nous_private FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA entre_nous_private TO entre_nous_app;

CREATE TABLE entre_nous_private.rooms (
    code text PRIMARY KEY, created double precision NOT NULL,
    touched double precision NOT NULL, state text NOT NULL
);
CREATE TABLE entre_nous_private.seats (
    token_hash bytea PRIMARY KEY, room text NOT NULL REFERENCES entre_nous_private.rooms(code) ON DELETE CASCADE,
    seat smallint NOT NULL CHECK (seat IN (0, 1)), seen double precision NOT NULL, UNIQUE(room, seat)
);
CREATE TABLE entre_nous_private.entry_limits (
    ip_hash bytea PRIMARY KEY, window_start timestamptz NOT NULL, attempts integer NOT NULL CHECK (attempts BETWEEN 1 AND 17)
);
CREATE INDEX rooms_expiry ON entre_nous_private.rooms(touched);
CREATE INDEX rooms_age ON entre_nous_private.rooms(created);
CREATE INDEX limits_expiry ON entre_nous_private.entry_limits(window_start);
REVOKE ALL ON ALL TABLES IN SCHEMA entre_nous_private FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA entre_nous_private TO entre_nous_app;
ALTER TABLE entre_nous_private.rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE entre_nous_private.seats ENABLE ROW LEVEL SECURITY;
ALTER TABLE entre_nous_private.entry_limits ENABLE ROW LEVEL SECURITY;
CREATE POLICY server_only ON entre_nous_private.rooms TO entre_nous_app USING (true) WITH CHECK (true);
CREATE POLICY server_only ON entre_nous_private.seats TO entre_nous_app USING (true) WITH CHECK (true);
CREATE POLICY server_only ON entre_nous_private.entry_limits TO entre_nous_app USING (true) WITH CHECK (true);

-- pg_cron doit être activé au préalable. Ce job utilise le rôle administrateur.
SELECT cron.schedule('entre-nous-purge-private-v1', '* * * * *', $job$
    DELETE FROM entre_nous_private.rooms
    WHERE touched <= extract(epoch FROM now()) - 1800 OR created <= extract(epoch FROM now()) - 21600;
    DELETE FROM entre_nous_private.entry_limits WHERE window_start <= now() - interval '2 minutes';
$job$);
COMMIT;
