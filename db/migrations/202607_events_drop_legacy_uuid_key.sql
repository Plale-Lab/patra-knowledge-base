-- ============================================================================
-- Migration: drop legacy single-column uuid uniqueness on events (Phase C of 3)
-- Date: 2026-07-16 (write time -- only APPLY this after Phase B has been
-- confirmed stable with real traffic; see 202607_events_composite_uuid_key_phase_a.sql
-- for full context on the bug and the three-phase rollout)
--
-- Prerequisite: the pgsink-oracle-events-connector's pk.fields must already be
-- "uuid,experiment_id" (Phase B) before running this. Until then, the legacy
-- single-column constraint dropped here is still needed as the ON CONFLICT
-- target for a connector still configured with pk.fields="uuid" -- dropping it
-- early would make every insert fail, not silently overwrite.
--
-- This is the step that actually closes the bug: two experiments can now
-- share an image filename with no error and no overwrite.
--
-- The legacy constraint's name is looked up dynamically rather than
-- hardcoded: it dates back to when this table was named camera_trap_events
-- (see db/migrations/prod_audit_apply.sql's RENAME), and Postgres does not
-- rename constraints/indexes when a table is renamed, so the live name is
-- camera_trap_events_uuid_key, not events_uuid_key (verified live via
-- pg_constraint). Looking it up dynamically also protects against the name
-- having changed again by the time this runs.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

BEGIN;

DO $$
DECLARE
  v_conname text;
BEGIN
  SELECT c.conname INTO v_conname
  FROM pg_constraint c
  WHERE c.conrelid = 'events'::regclass
    AND c.contype = 'u'
    AND array_length(c.conkey, 1) = 1
    AND c.conkey[1] = (
      SELECT attnum FROM pg_attribute
      WHERE attrelid = 'events'::regclass AND attname = 'uuid'
    );

  IF v_conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE events DROP CONSTRAINT %I', v_conname);
  END IF;
END
$$;

COMMIT;
