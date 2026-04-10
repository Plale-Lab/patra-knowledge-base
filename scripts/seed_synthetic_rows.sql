-- Synthetic seed data for all tables in db/schema.dbml
-- Run this in PostgreSQL (e.g., DBeaver SQL editor connected to patradbeaver DB).

BEGIN;

DO $$
DECLARE
  v_now timestamptz := now();

  v_user_id bigint;
  v_edge_device_id bigint;
  v_dataset_schema_id bigint;
  v_publisher_id bigint;
  v_model_card_id bigint;
  v_datasheet_id bigint;
  v_model_id bigint;
  v_experiment_id bigint;
  v_raw_image_id bigint;
BEGIN
  INSERT INTO users (created_at, updated_at)
  VALUES (v_now, v_now)
  RETURNING id INTO v_user_id;

  INSERT INTO edge_devices (created_at, updated_at)
  VALUES (v_now, v_now)
  RETURNING id INTO v_edge_device_id;

  INSERT INTO dataset_schemas (blob, created_at, updated_at)
  VALUES (
    '{"schema":"synthetic","fields":[{"name":"image","type":"string"},{"name":"label","type":"string"}]}'::jsonb,
    v_now,
    v_now
  )
  RETURNING id INTO v_dataset_schema_id;

  INSERT INTO publishers (
    name,
    publisher_identifier,
    publisher_identifier_scheme,
    scheme_uri,
    lang
  )
  VALUES (
    'Synthetic Publisher',
    'SYN-PUB-001',
    'internal',
    'https://example.org/publisher-scheme',
    'en'
  )
  RETURNING id INTO v_publisher_id;

  INSERT INTO model_cards (
    name,
    version,
    is_private,
    is_gated,
    status,
    short_description,
    full_description,
    keywords,
    author,
    citation,
    input_data,
    input_type,
    output_data,
    foundational_model,
    category,
    documentation,
    created_at,
    updated_at
  )
  VALUES (
    'Synthetic Model Card',
    '1.0.0',
    false,
    false,
    'approved',
    'Synthetic model card for testing.',
    'Detailed synthetic model card used for integration and UI tests.',
    'synthetic,test,seed',
    'Patra QA',
    'Patra QA (2026)',
    'Synthetic image dataset',
    'image',
    'Classification labels',
    'Synthetic Foundation v1',
    'computer_vision',
    'https://example.org/model-card-docs',
    v_now,
    v_now
  )
  RETURNING id INTO v_model_card_id;

  INSERT INTO datasheets (
    publication_year,
    resource_type,
    resource_type_general,
    size,
    format,
    version,
    is_private,
    status,
    created_at,
    updated_at,
    dataset_schema_id,
    publisher_id
  )
  VALUES (
    2026,
    'Dataset',
    'Dataset',
    '1000 images',
    'application/json',
    '1.0',
    false,
    'approved',
    v_now,
    v_now,
    v_dataset_schema_id,
    v_publisher_id
  )
  RETURNING identifier INTO v_datasheet_id;

  INSERT INTO datasheet_creators (
    datasheet_id,
    creator_name,
    name_type,
    lang,
    given_name,
    family_name,
    name_identifier,
    name_identifier_scheme,
    name_id_scheme_uri,
    affiliation,
    affiliation_identifier,
    affiliation_identifier_scheme,
    affiliation_scheme_uri
  )
  VALUES (
    v_datasheet_id,
    'Alex Synthetic',
    'Personal',
    'en',
    'Alex',
    'Synthetic',
    '0000-0000-0000-0001',
    'ORCID',
    'https://orcid.org',
    'Patra Labs',
    'GRID-12345',
    'GRID',
    'https://grid.ac'
  );

  INSERT INTO datasheet_titles (datasheet_id, title, title_type, lang)
  VALUES (v_datasheet_id, 'Synthetic Dataset Datasheet', 'MainTitle', 'en');

  INSERT INTO datasheet_subjects (
    datasheet_id,
    subject,
    subject_scheme,
    scheme_uri,
    value_uri,
    classification_code,
    lang
  )
  VALUES (
    v_datasheet_id,
    'Computer Vision',
    'LCSH',
    'https://id.loc.gov',
    'https://id.loc.gov/authorities/subjects/sh85029534',
    'CV-001',
    'en'
  );

  INSERT INTO datasheet_contributors (
    datasheet_id,
    contributor_type,
    contributor_name,
    name_type,
    given_name,
    family_name,
    name_identifier,
    name_identifier_scheme,
    name_id_scheme_uri,
    affiliation,
    affiliation_identifier,
    affiliation_identifier_scheme,
    affiliation_scheme_uri
  )
  VALUES (
    v_datasheet_id,
    'DataCurator',
    'Jordan Contributor',
    'Personal',
    'Jordan',
    'Contributor',
    '0000-0000-0000-0002',
    'ORCID',
    'https://orcid.org',
    'Patra Labs',
    'GRID-12345',
    'GRID',
    'https://grid.ac'
  );

  INSERT INTO datasheet_dates (datasheet_id, date, date_type, date_information)
  VALUES (v_datasheet_id, '2026-04-10', 'Issued', 'Synthetic issue date');

  INSERT INTO datasheet_alternate_identifiers (
    datasheet_id,
    alternate_identifier,
    alternate_identifier_type
  )
  VALUES (v_datasheet_id, 'ALT-SYN-001', 'Internal');

  INSERT INTO datasheet_related_identifiers (
    datasheet_id,
    related_identifier,
    related_identifier_type,
    relation_type,
    related_metadata_scheme,
    scheme_uri,
    scheme_type,
    resource_type_general
  )
  VALUES (
    v_datasheet_id,
    '10.1234/synthetic.related.001',
    'DOI',
    'IsReferencedBy',
    'DataCite',
    'https://doi.org',
    'DOI',
    'Text'
  );

  INSERT INTO datasheet_rights (
    datasheet_id,
    rights,
    rights_uri,
    rights_identifier,
    rights_identifier_scheme,
    scheme_uri,
    lang
  )
  VALUES (
    v_datasheet_id,
    'CC-BY 4.0',
    'https://creativecommons.org/licenses/by/4.0/',
    'cc-by-4.0',
    'SPDX',
    'https://spdx.org/licenses/',
    'en'
  );

  INSERT INTO datasheet_descriptions (datasheet_id, description, description_type, lang)
  VALUES (
    v_datasheet_id,
    'Synthetic datasheet description for test fixtures and QA flows.',
    'Abstract',
    'en'
  );

  INSERT INTO datasheet_geo_locations (
    datasheet_id,
    geo_location_place,
    point_longitude,
    point_latitude,
    box_west,
    box_east,
    box_south,
    box_north,
    polygon
  )
  VALUES (
    v_datasheet_id,
    'Test City',
    77.5946,
    12.9716,
    77.50,
    77.70,
    12.90,
    13.05,
    '{"type":"Polygon","coordinates":[[[77.50,12.90],[77.70,12.90],[77.70,13.05],[77.50,13.05],[77.50,12.90]]]}'::jsonb
  );

  INSERT INTO datasheet_funding_references (
    datasheet_id,
    funder_name,
    funder_identifier,
    funder_identifier_type,
    scheme_uri,
    award_number,
    award_uri,
    award_title
  )
  VALUES (
    v_datasheet_id,
    'Synthetic Research Council',
    'FUND-001',
    'Crossref Funder ID',
    'https://doi.org',
    'AWD-2026-001',
    'https://example.org/awards/AWD-2026-001',
    'Synthetic Data Initiative'
  );

  INSERT INTO models (
    name,
    version,
    description,
    owner,
    location,
    license,
    framework,
    model_type,
    test_accuracy,
    model_metrics,
    inference_labels,
    model_structure,
    created_at,
    updated_at,
    model_card_id
  )
  VALUES (
    'Synthetic Vision Model',
    '1.0.0',
    'A synthetic model used for integration testing.',
    'Patra QA',
    's3://patra/models/synthetic-vision-model',
    'MIT',
    'PyTorch',
    'classifier',
    0.93456,
    '{"precision":0.91,"recall":0.89,"f1":0.90}'::jsonb,
    '["cat","dog","other"]'::jsonb,
    '{"layers":[{"type":"conv","filters":32},{"type":"dense","units":128}]}'::jsonb,
    v_now,
    v_now,
    v_model_card_id
  )
  RETURNING id INTO v_model_id;

  INSERT INTO experiments (
    start_at,
    submitted_at,
    executed_at,
    model_used_at,
    total_images,
    total_predictions,
    total_ground_truth_objects,
    true_positives,
    false_positives,
    false_negatives,
    precision,
    recall,
    f1_score,
    mean_iou,
    map_50,
    map_50_95,
    created_at,
    updated_at,
    user_id,
    edge_device_id,
    model_id
  )
  VALUES (
    v_now - interval '2 hours',
    v_now - interval '90 minutes',
    v_now - interval '80 minutes',
    v_now - interval '75 minutes',
    250,
    240,
    230,
    200,
    20,
    30,
    0.90909,
    0.86957,
    0.88889,
    0.71234,
    0.83456,
    0.70123,
    v_now,
    v_now,
    v_user_id,
    v_edge_device_id,
    v_model_id
  )
  RETURNING id INTO v_experiment_id;

  INSERT INTO raw_images (
    image_name,
    ground_truth,
    created_at,
    updated_at
  )
  VALUES (
    'synthetic_image_001.jpg',
    '{"objects":[{"label":"cat","bbox":[0.1,0.2,0.4,0.6]}]}'::jsonb,
    v_now,
    v_now
  )
  RETURNING id INTO v_raw_image_id;

  INSERT INTO experiment_images (
    experiment_id,
    raw_image_id,
    image_count,
    image_received_at,
    image_scored_at,
    image_store_deleted_at,
    image_decision,
    top_label,
    top_probability,
    ingested_at,
    scores
  )
  VALUES (
    v_experiment_id,
    v_raw_image_id,
    1,
    v_now - interval '70 minutes',
    v_now - interval '69 minutes',
    NULL,
    'accepted',
    'cat',
    0.9712345,
    v_now - interval '68 minutes',
    '{"cat":0.9712345,"dog":0.0200000,"other":0.0087655}'::jsonb
  );

  INSERT INTO experiments (
    start_at,
    submitted_at,
    executed_at,
    model_used_at,
    total_images,
    total_predictions,
    total_ground_truth_objects,
    true_positives,
    false_positives,
    false_negatives,
    precision,
    recall,
    f1_score,
    mean_iou,
    map_50,
    map_50_95,
    created_at,
    updated_at,
    user_id,
    edge_device_id,
    model_id
  )
  VALUES (
    v_now - interval '5 hours',
    v_now - interval '4 hours 45 minutes',
    v_now - interval '4 hours 35 minutes',
    v_now - interval '4 hours 30 minutes',
    180,
    170,
    165,
    142,
    16,
    23,
    0.89873,
    0.86061,
    0.87926,
    0.69421,
    0.81234,
    0.67210,
    v_now,
    v_now,
    v_user_id,
    v_edge_device_id,
    v_model_id
  )
  RETURNING id INTO v_experiment_id;

  INSERT INTO raw_images (
    image_name,
    ground_truth,
    created_at,
    updated_at
  )
  VALUES (
    'synthetic_image_002.jpg',
    '{"objects":[{"label":"dog","bbox":[0.2,0.25,0.55,0.72]}]}'::jsonb,
    v_now,
    v_now
  )
  RETURNING id INTO v_raw_image_id;

  INSERT INTO experiment_images (
    experiment_id,
    raw_image_id,
    image_count,
    image_received_at,
    image_scored_at,
    image_store_deleted_at,
    image_decision,
    top_label,
    top_probability,
    ingested_at,
    scores
  )
  VALUES (
    v_experiment_id,
    v_raw_image_id,
    1,
    v_now - interval '4 hours 20 minutes',
    v_now - interval '4 hours 19 minutes',
    NULL,
    'accepted',
    'dog',
    0.9421000,
    v_now - interval '4 hours 18 minutes',
    '{"cat":0.0320000,"dog":0.9421000,"other":0.0259000}'::jsonb
  );

  INSERT INTO experiments (
    start_at,
    submitted_at,
    executed_at,
    model_used_at,
    total_images,
    total_predictions,
    total_ground_truth_objects,
    true_positives,
    false_positives,
    false_negatives,
    precision,
    recall,
    f1_score,
    mean_iou,
    map_50,
    map_50_95,
    created_at,
    updated_at,
    user_id,
    edge_device_id,
    model_id
  )
  VALUES (
    v_now - interval '9 hours',
    v_now - interval '8 hours 40 minutes',
    v_now - interval '8 hours 30 minutes',
    v_now - interval '8 hours 25 minutes',
    320,
    305,
    298,
    256,
    29,
    42,
    0.89825,
    0.85906,
    0.87821,
    0.73310,
    0.84620,
    0.70990,
    v_now,
    v_now,
    v_user_id,
    v_edge_device_id,
    v_model_id
  )
  RETURNING id INTO v_experiment_id;

  INSERT INTO raw_images (
    image_name,
    ground_truth,
    created_at,
    updated_at
  )
  VALUES (
    'synthetic_image_003.jpg',
    '{"objects":[{"label":"other","bbox":[0.15,0.18,0.63,0.70]}]}'::jsonb,
    v_now,
    v_now
  )
  RETURNING id INTO v_raw_image_id;

  INSERT INTO experiment_images (
    experiment_id,
    raw_image_id,
    image_count,
    image_received_at,
    image_scored_at,
    image_store_deleted_at,
    image_decision,
    top_label,
    top_probability,
    ingested_at,
    scores
  )
  VALUES (
    v_experiment_id,
    v_raw_image_id,
    1,
    v_now - interval '8 hours 15 minutes',
    v_now - interval '8 hours 14 minutes',
    NULL,
    'rejected',
    'other',
    0.9015000,
    v_now - interval '8 hours 13 minutes',
    '{"cat":0.0412000,"dog":0.0573000,"other":0.9015000}'::jsonb
  );
END $$;

COMMIT;
