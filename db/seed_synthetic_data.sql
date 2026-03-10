-- Production-like seed data for Patra Knowledge Graph (PostgreSQL)
--
-- Row counts:
--   users: 6, edge_devices: 3, model_cards: 10 (5 public, 5 private),
--   models: 10, datasheets: 10 (5 public, 5 private)
--
-- Usage:
--   psql -d your_database -f db/seed_synthetic_data.sql

BEGIN;

TRUNCATE TABLE
  experiment_images,
  deployments,
  experiments,
  raw_images,
  datasheets,
  models,
  model_cards,
  dataset_schemas,
  edge_devices,
  users
RESTART IDENTITY CASCADE;

--------------------------------------------------------------------------------
-- 1. users
--------------------------------------------------------------------------------
INSERT INTO users (id) VALUES
  ('nkarthikeyan'),
  ('wqiu'),
  ('jstubbs'),
  ('cgarcia'),
  ('rcardone'),
  ('skhuvis');

--------------------------------------------------------------------------------
-- 2. edge_devices
--------------------------------------------------------------------------------
INSERT INTO edge_devices (id) VALUES
  ('jetson_nano_01'),
  ('rpi4_cam_01'),
  ('coral_tpu_01');

--------------------------------------------------------------------------------
-- 3. model_cards  (5 public + 5 private)
--------------------------------------------------------------------------------
INSERT INTO model_cards (
  id, name, version, is_private,
  short_description, full_description,
  keywords, author, citation,
  input_data, input_type, output_data,
  foundational_model, category, documentation
) VALUES
  -- PUBLIC (5)
  ('43d851cd-a509-49e3-8416-50b344b174ed',
   'HybridEnd2EndLearner', '5a', false,
   'HybridEnd2EndLearner 97% MNIST Dataset',
   'End-to-end hybrid quantum-classical learner achieving 97% accuracy on the MNIST handwritten digit dataset.',
   'hybrid,quantum,mnist,classification', 'nkarthikeyan',
   'Karthikeyan et al., 2024. HybridEnd2EndLearner for MNIST.',
   'MNIST 28×28 grayscale images', 'images', 'digit class probabilities',
   'HybridEnd2EndLearner', 'classification', ''),

  ('41d3ed40-b836-4a62-b3fb-67cee79f33d9',
   'MegaDetector for Wildlife Detection', '5a', false,
   'Wildlife detection using MegaDetector from Microsoft.',
   'MegaDetector v5a is a camera-trap image detector from Microsoft AI for Earth.',
   'wildlife,camera trap,megadetector,object detection', 'wqiu',
   'Beery et al., 2019. Efficient Pipeline for Camera Trap Image Review. arXiv:1907.06772',
   'Camera trap images', 'images', 'Bounding boxes (animal, person, vehicle)',
   'MegaDetector', 'detection', ''),

  ('ec3f6227-14c5-4873-96d7-14ddcaf9b34a',
   'GoogLeNet for Image Classification', '1.0', false,
   'Image classification using GoogLeNet.',
   'GoogLeNet (Inception v1) pre-trained on ImageNet for general-purpose image classification.',
   'googlenet,inception,classification,imagenet', 'jstubbs',
   'Szegedy et al., 2015. Going Deeper with Convolutions. CVPR 2015.',
   'https://image-net.org/', 'images', 'ImageNet class probabilities',
   'GoogLeNet', 'classification', ''),

  ('0556d19e-b478-4a89-bd74-a2d822e97a8a',
   'ResNet50 Image Classification Model', '1.0', false,
   'Pre-trained ResNet50 model from torchvision for image classification.',
   'Pre-trained ResNet50 from torchvision, fine-tuned for general image classification benchmarks.',
   'resnet50,classification,torchvision,imagenet', 'cgarcia',
   'He et al., 2016. Deep Residual Learning for Image Recognition. CVPR 2016.',
   'https://image-net.org/', 'images', 'ImageNet class probabilities',
   'ResNet50', 'classification', ''),

  ('0cddbc64-75f7-4aee-a91d-c27583415bbc',
   'Ultralytics YOLO', '9e', false,
   'YOLOv9',
   'YOLOv9 marks a significant advancement in real-time object detection, introducing PGI and GELAN.',
   'yolo, ultralytics, object detection', 'skhuvis',
   'YOLOv9: Learning What You Want to Learn Using Programmable Gradient Information (arXiv:2402.13616)',
   'https://cocodataset.org/', 'images', '',
   'YOLOv5', 'classification', ''),

  -- PRIVATE (5)
  ('5356e5ba-b700-449a-ace3-ddecbce7a30a',
   'MegaDetector for Wildlife Detection', '5a (OSA finetuning)', true,
   'Wildlife detection using MegaDetector from Microsoft.',
   'MegaDetector v5a fine-tuned on the OSA (Open Science Alliance) camera trap dataset.',
   'wildlife,camera trap,megadetector,finetuned,osa', 'rcardone',
   'Beery et al., 2019. Efficient Pipeline for Camera Trap Image Review. arXiv:1907.06772',
   'Camera trap images', 'images', 'Bounding boxes (animal, person, vehicle)',
   'MegaDetector', 'detection', ''),

  ('2983330b-28a4-4fb5-816d-aee0e421cb72',
   'MegaDetector for Wildlife Detection', '6b-yolov9c', true,
   'Wildlife detection using MegaDetector from Microsoft.',
   'MegaDetector v6b built on YOLOv9c backbone for improved speed-accuracy trade-off.',
   'wildlife,camera trap,megadetector,yolov9', 'wqiu',
   'Beery et al., 2019. Efficient Pipeline for Camera Trap Image Review. arXiv:1907.06772',
   'Camera trap images', 'images', 'Bounding boxes (animal, person, vehicle)',
   'YOLOv9c', 'detection', ''),

  ('de221f7c-5c78-4375-b9f0-617884b75aa5',
   'Yolo Object Detecion - for detecting a soft toy',
   'yolo11l_ep1_bs32_lr0.005_8aa95a86.pt', true,
   'Detecting Soft toys in frame usining fine-tuned yolo model',
   'YOLOv11-large fine-tuned to detect soft toys in camera frames for inventory counting.',
   'yolo,object detection,soft toy,inventory', 'skhuvis',
   '', 'Camera frames', 'images', 'Bounding boxes with confidence',
   'YOLOv11', 'detection', ''),

  ('687437a9-aa0a-4255-a350-2cd6b822affd',
   'Ultralytics YOLO26n', '6b-yolov9c', true,
   'YOLO26n.',
   'YOLO26 is the latest evolution in the YOLO series, engineered for edge and low-power devices.',
   'yolo, ultralytics, object detection', 'skhuvis',
   'https://huggingface.co/Ultralytics/YOLO26',
   'https://cocodataset.org/', 'images', '',
   'YOLO26', 'classification', ''),

  ('4e7f645d-9c64-4fc6-b67d-04eb0a4ce44a',
   'Ultralytics YOLO26x', '26x', true,
   'YOLO26x.',
   'YOLO26x is the extra-large variant of YOLO26 for maximum accuracy on high-resolution inputs.',
   'yolo, ultralytics, object detection, yolo26', 'skhuvis',
   'https://huggingface.co/Ultralytics/YOLO26',
   'https://cocodataset.org/', 'images', '',
   'YOLO26', 'classification', '');

--------------------------------------------------------------------------------
-- 4. models  (1:1 with model_cards)
--------------------------------------------------------------------------------
INSERT INTO models (
  id, name, version, description, owner, location, license,
  framework, model_type, test_accuracy, model_card_id
) VALUES
  ('43d851cd-a509-49e3-8416-50b344b174ed-model',
   'HybridEnd2EndLearner', '5a',
   'Hybrid quantum-classical model for digit classification.',
   'ICICLE', '', 'MIT', 'PennyLane', 'hybrid quantum-classical', 0.97,
   '43d851cd-a509-49e3-8416-50b344b174ed'),

  ('41d3ed40-b836-4a62-b3fb-67cee79f33d9-model',
   'MegaDetector', '5a',
   'Camera-trap animal/person/vehicle detector.',
   'Microsoft AI for Earth',
   'https://github.com/microsoft/CameraTraps/releases/download/v5.0/md_v5a.0.0.pt',
   'MIT', 'PyTorch', 'convolutional neural network', 0.89,
   '41d3ed40-b836-4a62-b3fb-67cee79f33d9'),

  ('ec3f6227-14c5-4873-96d7-14ddcaf9b34a-model',
   'GoogLeNet', '1.0',
   'Inception v1 pre-trained on ImageNet.',
   'torchvision', '', 'BSD-3-Clause', 'PyTorch', 'convolutional neural network', 0.74,
   'ec3f6227-14c5-4873-96d7-14ddcaf9b34a'),

  ('0556d19e-b478-4a89-bd74-a2d822e97a8a-model',
   'ResNet50', '1.0',
   'Pre-trained ResNet50 from torchvision.',
   'torchvision', '', 'BSD-3-Clause', 'PyTorch', 'convolutional neural network', 0.76,
   '0556d19e-b478-4a89-bd74-a2d822e97a8a'),

  ('0cddbc64-75f7-4aee-a91d-c27583415bbc-model',
   'YOLO', '9e',
   'A convolutional neural network model for object detection.',
   'Ultralytics',
   'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov9e.pt',
   'AGPL-3.0 License', 'PyTorch', 'convolutional neural network', 0.85,
   '0cddbc64-75f7-4aee-a91d-c27583415bbc'),

  ('5356e5ba-b700-449a-ace3-ddecbce7a30a-model',
   'MegaDetector', '5a-osa',
   'OSA fine-tuned MegaDetector v5a.',
   'ICICLE', '', 'MIT', 'PyTorch', 'convolutional neural network', 0.92,
   '5356e5ba-b700-449a-ace3-ddecbce7a30a'),

  ('2983330b-28a4-4fb5-816d-aee0e421cb72-model',
   'MegaDetector', '6b-yolov9c',
   'YOLOv9c backbone for better speed-accuracy.',
   'Microsoft AI for Earth', '', 'MIT', 'PyTorch', 'convolutional neural network', 0.90,
   '2983330b-28a4-4fb5-816d-aee0e421cb72'),

  ('de221f7c-5c78-4375-b9f0-617884b75aa5-model',
   'YOLO11L SoftToy', 'yolo11l_ep1_bs32_lr0.005',
   'YOLOv11-large fine-tuned for soft toy detection.',
   'skhuvis', '', 'AGPL-3.0 License', 'PyTorch', 'convolutional neural network', 0.82,
   'de221f7c-5c78-4375-b9f0-617884b75aa5'),

  ('687437a9-aa0a-4255-a350-2cd6b822affd-model',
   'YOLO', '26n',
   'A convolutional neural network model for object detection.',
   'Ultralytics',
   'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt',
   'AGPL-3.0 License', 'PyTorch', 'convolutional neural network', 0.85,
   '687437a9-aa0a-4255-a350-2cd6b822affd'),

  ('4e7f645d-9c64-4fc6-b67d-04eb0a4ce44a-model',
   'YOLO', '26x',
   'Extra-large YOLO26 for maximum accuracy.',
   'Ultralytics',
   'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26x.pt',
   'AGPL-3.0 License', 'PyTorch', 'convolutional neural network', 0.88,
   '4e7f645d-9c64-4fc6-b67d-04eb0a4ce44a');

--------------------------------------------------------------------------------
-- 5. datasheets  (5 public + 5 private)
--------------------------------------------------------------------------------
INSERT INTO datasheets (
  identifier, creator, title, publisher, publication_year,
  resource_type, size, format, version, rights, description,
  geo_location, category, is_private
) OVERRIDING SYSTEM VALUE VALUES
  -- PUBLIC (5)
  (1, 'wqiu', 'LILA Camera Traps', 'LILA BC',
   2021, 'images', '3 TB', 'jpeg', '1.0', 'public',
   'Labelled camera-trap images from LILA BC.',
   'global', 'wildlife', false),

  (2, 'jstubbs', 'ImageNet-1K', 'Stanford / Princeton',
   2012, 'images', '150 GB', 'jpeg', '1.0', 'academic',
   '1000-class subset of the ImageNet dataset.',
   'global', 'classification', false),

  (3, 'nkarthikeyan', 'MNIST', 'NYU',
   1998, 'images', '50 MB', 'idx', '1.0', 'public',
   'Handwritten digit images 0-9.',
   'global', 'classification', false),

  (4, 'skhuvis', 'MS COCO 2017', 'cocodataset.org',
   2017, 'images', '25 GB', 'jpeg', '2017', 'CC BY 4.0',
   'Common Objects in Context detection/segmentation dataset.',
   'global', 'detection', false),

  (5, 'cgarcia', 'ImageNet ResNet Subset', 'Stanford / Princeton',
   2015, 'images', '12 GB', 'jpeg', '1.0', 'academic',
   'Curated ImageNet subset for ResNet50 benchmarking.',
   'global', 'classification', false),

  -- PRIVATE (5)
  (6, 'rcardone', 'OSA Camera Traps', 'Open Science Alliance',
   2024, 'images', '18 GB', 'jpeg', '1.0', 'research-only',
   'OSA partner camera-trap imagery for fine-tuning.',
   'US', 'wildlife', true),

  (7, 'wqiu', 'ENA Wildlife Survey', 'ICICLE',
   2024, 'images', '32 GB', 'jpeg', '1.0', 'research-only',
   'Endangered North American species camera-trap survey.',
   'US', 'wildlife', true),

  (8, 'skhuvis', 'Soft Toy Inventory Frames', 'Internal',
   2025, 'images', '2 GB', 'jpeg', '1.0', 'internal',
   'Camera frames labelled with soft-toy bounding boxes.',
   'US', 'detection', true),

  (9, 'skhuvis', 'YOLO26 Edge Benchmark', 'Ultralytics',
   2025, 'images', '8 GB', 'jpeg', '1.0', 'internal',
   'Edge device evaluation images for YOLO26n benchmarking.',
   'global', 'detection', true),

  (10, 'skhuvis', 'YOLO26x High-Res Evaluation', 'Ultralytics',
   2025, 'images', '45 GB', 'png', '1.0', 'internal',
   'High-resolution evaluation set for YOLO26x accuracy testing.',
   'global', 'detection', true);

COMMIT;
