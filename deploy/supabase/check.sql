-- Contrôle en lecture seule, dans le projet qui héberge Entre nous.
DO $check$
DECLARE
  target regclass;
  client_role name;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'entre_nous_app' AND (rolbypassrls OR rolsuper)) THEN
    RAISE EXCEPTION 'Le rôle applicatif est trop privilégié.';
  END IF;
  FOREACH target IN ARRAY ARRAY[
    'entre_nous_private.rooms'::regclass,
    'entre_nous_private.seats'::regclass,
    'entre_nous_private.entry_limits'::regclass
  ] LOOP
    IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = target) THEN
      RAISE EXCEPTION 'RLS inactive.';
    END IF;
    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']::name[] LOOP
      IF has_schema_privilege(client_role, 'entre_nous_private', 'USAGE')
         OR has_table_privilege(client_role, target, 'SELECT,INSERT,UPDATE,DELETE') THEN
        RAISE EXCEPTION 'Un rôle public peut accéder aux tables privées.';
      END IF;
    END LOOP;
    IF NOT (has_table_privilege('entre_nous_app', target, 'SELECT')
      AND has_table_privilege('entre_nous_app', target, 'INSERT')
      AND has_table_privilege('entre_nous_app', target, 'UPDATE'))
      OR has_table_privilege('entre_nous_app', target, 'DELETE') THEN
      RAISE EXCEPTION 'Privilèges du serveur incohérents.';
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'entre-nous-purge-private-v1' AND active) THEN
    RAISE EXCEPTION 'Purge absente ou inactive.';
  END IF;
END;
$check$;
