-- ============================================================================
-- Migration: model_cards.training_datasheet_id (last trained/fine-tuned dataset)
-- Date: 2026-07-18
--
-- Problem:
-- PATRA manages both model cards and datasheets, but nothing links a model
-- card to the dataset it was last trained or fine-tuned on. Participants at
-- the PEARC/PERC tutorial will naturally ask how the two are connected, and
-- today there is no answer.
--
-- Fix:
-- Add a nullable FK from model_cards to the datasheet it was last trained or
-- fine-tuned on. This is a cross-entity, non-owning link (not a parent/child
-- row like the datasheet_* child tables), so ON DELETE SET NULL: deleting the
-- referenced datasheet clears the link instead of blocking the delete or
-- cascading into the model card. The externally-visible identifier is the
-- datasheet's uuid; this column stores the internal bigint (datasheets.identifier),
-- converted at the API route boundary the same way model_cards.uuid/id are.
--
-- This same statement is mirrored in db/bootstrap_schema.sql for fresh installs.
--
-- Idempotent. Safe to re-run (ADD COLUMN IF NOT EXISTS skips entirely, so the
-- inline FK/index are never duplicated on re-run).
-- ============================================================================

BEGIN;

ALTER TABLE model_cards
  ADD COLUMN IF NOT EXISTS training_datasheet_id bigint
    REFERENCES datasheets(identifier) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_model_cards_training_datasheet_id
  ON model_cards (training_datasheet_id);

COMMIT;
