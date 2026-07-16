-- ============================================================================
-- Migration: add composite (experiment_id, uuid) uniqueness to events (Phase A of 3)
-- Date: 2026-07-16
--
-- Problem:
-- image_generating_plugin derives each image's `uuid` deterministically from
-- its filename (uuid5(NAMESPACE_URL, file_name)), so the same filename always
-- produces the same uuid regardless of which experiment or user processes it.
-- Combined with events.uuid being a single-column UNIQUE constraint
-- (camera_trap_events_uuid_key -- a leftover name from before this table was
-- renamed from camera_trap_events; Postgres doesn't rename constraints on
-- table rename), the JDBC sink's `ON CONFLICT (uuid) DO UPDATE` silently
-- overwrites an older experiment's row (including its experiment_id/user_id)
-- whenever a newer experiment processes a same-named image. This is what a
-- user (Samuel Khuvis) observed as his dashboard "overwriting" older
-- experiments -- the dashboard's summary/list endpoints query `events`
-- directly (grouped by experiment_id), so a collided row makes that
-- experiment vanish from the dashboard even though the normalized
-- `experiments` table (keyed on the real per-run experiment_uid) is untouched.
--
-- Fix, in three phases to avoid an ingest-outage window (Postgres requires an
-- ON CONFLICT target to exactly match an existing constraint, so swapping the
-- schema and the connector config in either order, atomically, creates a gap
-- where every insert fails):
--   Phase A (this file): add UNIQUE(experiment_id, uuid) alongside the
--     existing single-column constraint. Purely additive -- uuid is already
--     globally unique today, so this superset is trivially unique too, no
--     data cleanup needed. Safe to apply any time, no connector coordination
--     required, since nothing reads this constraint as an ON CONFLICT target
--     yet.
--   Phase B (separate step, coordinate with the team first -- this is the
--     step that actually changes ingest behavior): flip the
--     pgsink-oracle-events-connector's pk.fields from "uuid" to
--     "uuid,experiment_id" via the Kafka Connect REST API, so ON CONFLICT
--     targets this new constraint. Zero-gap cutover since the constraint
--     already exists by the time this lands.
--   Phase C (separate migration, after B has soaked with real traffic): drop
--     the legacy single-column constraint -- see
--     202607_events_drop_legacy_uuid_key.sql. This is the point the bug is
--     fully closed; until then, a real collision hard-fails instead of
--     silently overwriting (a strict improvement even before Phase C).
--
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block, so this
-- file intentionally has no BEGIN/COMMIT wrapper -- psql runs each top-level
-- statement in its own implicit transaction by default.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS events_experiment_id_uuid_key
  ON events (experiment_id, uuid);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'events_experiment_id_uuid_key') THEN
    ALTER TABLE events ADD CONSTRAINT events_experiment_id_uuid_key
      UNIQUE USING INDEX events_experiment_id_uuid_key;
  END IF;
END
$$;
