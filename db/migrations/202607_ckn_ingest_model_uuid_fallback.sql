-- ============================================================================
-- Migration: CKN ingest trigger accepts camera-traps' native model_id (UUID)
-- Date: 2026-07-15
--
-- Problem:
-- fn_ingest_camera_trap_event() only resolves NEW.model_id against the
-- numeric models.id bigint. But camera-traps' own installer defaults and
-- image_generating_plugin always send a Patra model-card UUID, optionally
-- suffixed "-model" (e.g. "ea991e85-feaa-4781-a297-4d7bec1a69b1-model") --
-- a convention the trigger has never understood, so any experiment using
-- those defaults fails CKN ingest for an already-registered model.
--
-- (History: models.ckn_model_id / models.model_uid used to store this UUID
-- form and the trigger used to auto-create unrecognized models. The
-- 2026-05-16 migration dropped ckn_auto_created flags and the following
-- day's MLHub migration dropped ckn_model_id/model_uid entirely, requiring
-- the raw bigint -- intentionally removing auto-creation, but as a side
-- effect also removing UUID resolution for models that ARE registered.)
--
-- Fix:
-- When the bigint lookup misses, fall back to resolving NEW.model_id as a
-- model_cards.uuid (stripping the optional "-model" suffix) via the existing
-- models.model_card_id FK. No auto-creation is reintroduced -- an
-- unregistered model still fails loudly.
--
-- Only step 3 (model resolution) changes; steps 1-2 and 4-7 are copied
-- unchanged from the deployed function so this CREATE OR REPLACE is a
-- like-for-like replacement plus the new fallback.
--
-- The trigger function is defined in db/bootstrap_schema.sql (CREATE OR
-- REPLACE FUNCTION is idempotent); this migration applies the same body to
-- an already-deployed database.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION fn_ingest_camera_trap_event() RETURNS trigger AS $fn$
DECLARE
  v_model_id bigint;
  v_experiment_id bigint;
  v_raw_image_id bigint;
  v_scores jsonb;
BEGIN
  -- 1. Verify user is pre-registered (users.username is the Tapis username).
  IF NOT EXISTS (SELECT 1 FROM users WHERE username = NEW.user_id) THEN
    RAISE EXCEPTION 'CKN ingest: user "%" not registered in patra (users.username)', NEW.user_id;
  END IF;

  -- 2. Verify edge_device is pre-registered (edge_devices.device_id).
  IF NOT EXISTS (SELECT 1 FROM edge_devices WHERE device_id = NEW.device_id) THEN
    RAISE EXCEPTION 'CKN ingest: edge_device "%" not registered in patra (edge_devices.device_id)', NEW.device_id;
  END IF;

  -- 3. Resolve model id. Two conventions arrive here:
  --    (a) the patradb models.id bigint, as text (e.g. "22")
  --    (b) camera-traps' native Patra model-card UUID, optionally suffixed "-model"
  --        (e.g. "ea991e85-feaa-4781-a297-4d7bec1a69b1-model") -- installer/compile.py's
  --        defaults and image_generating_plugin always send this form.
  SELECT id INTO v_model_id FROM models WHERE id::text = NEW.model_id;

  IF v_model_id IS NULL THEN
    SELECT m.id INTO v_model_id
    FROM models m
    JOIN model_cards mc ON mc.id = m.model_card_id
    WHERE mc.uuid::text = regexp_replace(NEW.model_id, '-model$', '');
  END IF;

  IF v_model_id IS NULL THEN
    RAISE EXCEPTION 'CKN ingest: model "%" not registered in patra (models.id or model_cards.uuid)', NEW.model_id;
  END IF;

  -- 4. Upsert experiment keyed on experiment_uid; on subsequent events,
  --    update running aggregates and extend executed_at forward.
  INSERT INTO experiments (
    experiment_uid, start_at, executed_at,
    total_images, total_predictions, total_ground_truth_objects,
    true_positives, false_positives, false_negatives,
    precision, recall, f1_score, mean_iou, map_50, map_50_95,
    user_id, edge_device_id, model_id
  )
  VALUES (
    NEW.experiment_id,
    COALESCE(NEW.image_receiving_timestamp, NOW()),
    NEW.image_scoring_timestamp,
    NEW.total_images, NEW.total_predictions, NEW.total_ground_truth_objects,
    NEW.true_positives, NEW.false_positives, NEW.false_negatives,
    NEW.precision, NEW.recall, NEW.f1_score, NEW.mean_iou, NEW.map_50, NEW.map_50_95,
    NEW.user_id, NEW.device_id, v_model_id
  )
  ON CONFLICT ON CONSTRAINT experiments_experiment_uid_key DO UPDATE SET
    executed_at = GREATEST(experiments.executed_at, EXCLUDED.executed_at),
    total_images = EXCLUDED.total_images,
    total_predictions = EXCLUDED.total_predictions,
    total_ground_truth_objects = EXCLUDED.total_ground_truth_objects,
    true_positives = EXCLUDED.true_positives,
    false_positives = EXCLUDED.false_positives,
    false_negatives = EXCLUDED.false_negatives,
    precision = EXCLUDED.precision,
    recall = EXCLUDED.recall,
    f1_score = EXCLUDED.f1_score,
    mean_iou = EXCLUDED.mean_iou,
    map_50 = EXCLUDED.map_50,
    map_50_95 = EXCLUDED.map_50_95
  RETURNING id INTO v_experiment_id;

  -- 5. Resolve or create raw_image keyed on the CKN event UUID
  INSERT INTO raw_images (image_uid, image_name, ground_truth)
  VALUES (
    NEW.uuid,
    COALESCE(NEW.image_name, NEW.uuid),
    CASE WHEN NEW.ground_truth IS NOT NULL
         THEN jsonb_build_object('label', NEW.ground_truth)
         ELSE NULL END
  )
  ON CONFLICT ON CONSTRAINT raw_images_image_uid_key DO UPDATE SET image_name = EXCLUDED.image_name
  RETURNING id INTO v_raw_image_id;

  -- 6. Parse flattened_scores if it's valid JSON; otherwise wrap the raw string.
  v_scores := NULL;
  IF NEW.flattened_scores IS NOT NULL THEN
    BEGIN
      v_scores := NEW.flattened_scores::jsonb;
    EXCEPTION WHEN OTHERS THEN
      v_scores := jsonb_build_object('raw', NEW.flattened_scores);
    END;
  END IF;

  -- 7. Upsert the experiment_images row for this (experiment, image) pair.
  INSERT INTO experiment_images (
    experiment_id, raw_image_id, image_count,
    image_received_at, image_scored_at, image_store_deleted_at,
    image_decision, top_label, top_probability,
    ingested_at, scores
  )
  VALUES (
    v_experiment_id, v_raw_image_id, COALESCE(NEW.image_count, 1),
    NEW.image_receiving_timestamp, NEW.image_scoring_timestamp, NEW.image_store_delete_time,
    NEW.image_decision, NEW.label, NEW.probability,
    COALESCE(NEW.ingested_at, NOW()), v_scores
  )
  ON CONFLICT (experiment_id, raw_image_id) DO UPDATE SET
    image_scored_at = EXCLUDED.image_scored_at,
    image_store_deleted_at = EXCLUDED.image_store_deleted_at,
    image_decision = EXCLUDED.image_decision,
    top_label = EXCLUDED.top_label,
    top_probability = EXCLUDED.top_probability,
    scores = EXCLUDED.scores;

  RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

COMMIT;
