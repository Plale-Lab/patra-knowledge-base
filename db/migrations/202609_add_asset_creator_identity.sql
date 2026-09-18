-- Card-level submission identity. These are deliberately nullable so existing
-- catalog records remain valid; new API submissions require both values.
BEGIN;

ALTER TABLE model_cards
  ADD COLUMN IF NOT EXISTS creator_tapis_id text,
  ADD COLUMN IF NOT EXISTS creator_name text;

ALTER TABLE datasheets
  ADD COLUMN IF NOT EXISTS creator_tapis_id text,
  ADD COLUMN IF NOT EXISTS creator_name text;

COMMIT;
