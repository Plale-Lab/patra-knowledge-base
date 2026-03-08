"""Seed the live Patra database with production-like data.

Matches db/schema.dbml: monotonically increasing integer IDs, audit timestamps,
optional datasheet.model_card_id. No deployments table.

Truncates tables (RESTART IDENTITY) and inserts 10 model cards (5 public, 5 private),
10 models, and 10 datasheets (5 public, 5 private; 2 without model_card_id).

Usage:
    DATABASE_URL="postgresql://…" python3 db/seed_production_like.py
"""

import asyncio
import os
import ssl
from datetime import datetime, timezone

import asyncpg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://patradb:zBQDRU23BVwoXh8zGh77eumDWOVR7c"
    "@patradb.pods.icicleai.tapis.io:443/patradb?sslmode=require",
)

# Single timestamp for all audit columns in this seed run
_NOW = datetime.now(timezone.utc)

# ── Model cards: 5 public + 5 private (no id – use serial 1..10) ─────────────
MODEL_CARDS = [
    # --- PUBLIC (5) ---
    {
        "name": "HybridEnd2EndLearner",
        "version": "5a",
        "is_private": False,
        "short_description": "HybridEnd2EndLearner 97% MNIST Dataset",
        "full_description": "End-to-end hybrid quantum-classical learner achieving 97% accuracy on the MNIST handwritten digit dataset.",
        "keywords": "hybrid,quantum,mnist,classification",
        "author": "nkarthikeyan",
        "citation": "Karthikeyan et al., 2024. HybridEnd2EndLearner for MNIST.",
        "input_data": "MNIST 28×28 grayscale images",
        "input_type": "images",
        "output_data": "digit class probabilities",
        "foundational_model": "HybridEnd2EndLearner",
        "category": "classification",
    },
    {
        "name": "MegaDetector for Wildlife Detection",
        "version": "5a",
        "is_private": False,
        "short_description": "Wildlife detection using MegaDetector from Microsoft.",
        "full_description": "MegaDetector v5a is a camera-trap image detector from Microsoft AI for Earth. It classifies images as containing animals, people, or vehicles.",
        "keywords": "wildlife,camera trap,megadetector,object detection",
        "author": "wqiu",
        "citation": "Beery et al., 2019. Efficient Pipeline for Camera Trap Image Review. arXiv:1907.06772",
        "input_data": "Camera trap images",
        "input_type": "images",
        "output_data": "Bounding boxes (animal, person, vehicle)",
        "foundational_model": "MegaDetector",
        "category": "detection",
    },
    {
        "name": "GoogLeNet for Image Classification",
        "version": "1.0",
        "is_private": False,
        "short_description": "Image classification using GoogLeNet.",
        "full_description": "GoogLeNet (Inception v1) pre-trained on ImageNet for general-purpose image classification.",
        "keywords": "googlenet,inception,classification,imagenet",
        "author": "jstubbs",
        "citation": "Szegedy et al., 2015. Going Deeper with Convolutions. CVPR 2015.",
        "input_data": "https://image-net.org/",
        "input_type": "images",
        "output_data": "ImageNet class probabilities",
        "foundational_model": "GoogLeNet",
        "category": "classification",
    },
    {
        "name": "ResNet50 Image Classification Model",
        "version": "1.0",
        "is_private": False,
        "short_description": "Pre-trained ResNet50 model from torchvision for image classification.",
        "full_description": "Pre-trained ResNet50 from torchvision, fine-tuned for general image classification benchmarks.",
        "keywords": "resnet50,classification,torchvision,imagenet",
        "author": "cgarcia",
        "citation": "He et al., 2016. Deep Residual Learning for Image Recognition. CVPR 2016.",
        "input_data": "https://image-net.org/",
        "input_type": "images",
        "output_data": "ImageNet class probabilities",
        "foundational_model": "ResNet50",
        "category": "classification",
    },
    {
        "name": "Ultralytics YOLO",
        "version": "9e",
        "is_private": False,
        "short_description": "YOLOv9",
        "full_description": "YOLOv9 marks a significant advancement in real-time object detection, introducing groundbreaking techniques such as Programmable Gradient Information (PGI) and the Generalized Efficient Layer Aggregation Network (GELAN).",
        "keywords": "yolo, ultralytics, object detection",
        "author": "skhuvis",
        "citation": "YOLOv9: Learning What You Want to Learn Using Programmable Gradient Information by Wang, Chien-Yao and Liao, Hong-Yuan Mark (arXiv:2402.13616)",
        "input_data": "https://cocodataset.org/",
        "input_type": "images",
        "output_data": "",
        "foundational_model": "YOLOv5",
        "category": "classification",
    },
    # --- PRIVATE (5) ---
    {
        "name": "MegaDetector for Wildlife Detection",
        "version": "5a (OSA finetuning)",
        "is_private": True,
        "short_description": "Wildlife detection using MegaDetector from Microsoft.",
        "full_description": "MegaDetector v5a fine-tuned on the OSA (Open Science Alliance) camera trap dataset.",
        "keywords": "wildlife,camera trap,megadetector,finetuned,osa",
        "author": "rcardone",
        "citation": "Beery et al., 2019. Efficient Pipeline for Camera Trap Image Review. arXiv:1907.06772",
        "input_data": "Camera trap images",
        "input_type": "images",
        "output_data": "Bounding boxes (animal, person, vehicle)",
        "foundational_model": "MegaDetector",
        "category": "detection",
    },
    {
        "name": "MegaDetector for Wildlife Detection",
        "version": "6b-yolov9c",
        "is_private": True,
        "short_description": "Wildlife detection using MegaDetector from Microsoft.",
        "full_description": "MegaDetector v6b built on YOLOv9c backbone for improved speed-accuracy trade-off.",
        "keywords": "wildlife,camera trap,megadetector,yolov9",
        "author": "wqiu",
        "citation": "Beery et al., 2019. Efficient Pipeline for Camera Trap Image Review. arXiv:1907.06772",
        "input_data": "Camera trap images",
        "input_type": "images",
        "output_data": "Bounding boxes (animal, person, vehicle)",
        "foundational_model": "YOLOv9c",
        "category": "detection",
    },
    {
        "name": "Yolo Object Detecion - for detecting a soft toy",
        "version": "yolo11l_ep1_bs32_lr0.005_8aa95a86.pt",
        "is_private": True,
        "short_description": "Detecting Soft toys in frame usining fine-tuned yolo model",
        "full_description": "YOLOv11-large fine-tuned to detect soft toys in camera frames for inventory counting.",
        "keywords": "yolo,object detection,soft toy,inventory",
        "author": "skhuvis",
        "citation": "",
        "input_data": "Camera frames",
        "input_type": "images",
        "output_data": "Bounding boxes with confidence",
        "foundational_model": "YOLOv11",
        "category": "detection",
    },
    {
        "name": "Ultralytics YOLO26n",
        "version": "6b-yolov9c",
        "is_private": True,
        "short_description": "YOLO26n.",
        "full_description": "YOLO26 is the latest evolution in the YOLO series of real-time object detectors, engineered from the ground up for edge and low-power devices.",
        "keywords": "yolo, ultralytics, object detection",
        "author": "skhuvis",
        "citation": "https://huggingface.co/Ultralytics/YOLO26",
        "input_data": "https://cocodataset.org/",
        "input_type": "images",
        "output_data": "",
        "foundational_model": "YOLO26",
        "category": "classification",
    },
    {
        "name": "Ultralytics YOLO26x",
        "version": "26x",
        "is_private": True,
        "short_description": "YOLO26x.",
        "full_description": "YOLO26x is the extra-large variant of YOLO26 designed for maximum accuracy on high-resolution inputs.",
        "keywords": "yolo, ultralytics, object detection, yolo26",
        "author": "skhuvis",
        "citation": "https://huggingface.co/Ultralytics/YOLO26",
        "input_data": "https://cocodataset.org/",
        "input_type": "images",
        "output_data": "",
        "foundational_model": "YOLO26",
        "category": "classification",
    },
]

# ── Models (1:1 with model cards; index i → model_card_id = i+1) ─────────────
MODELS = [
    {"name": "HybridEnd2EndLearner", "version": "5a", "description": "Hybrid quantum-classical model for digit classification.", "owner": "ICICLE", "location": "", "license": "MIT", "framework": "PennyLane", "model_type": "hybrid quantum-classical", "test_accuracy": 0.97},
    {"name": "MegaDetector", "version": "5a", "description": "Camera-trap animal/person/vehicle detector.", "owner": "Microsoft AI for Earth", "location": "https://github.com/microsoft/CameraTraps/releases/download/v5.0/md_v5a.0.0.pt", "license": "MIT", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.89},
    {"name": "GoogLeNet", "version": "1.0", "description": "Inception v1 pre-trained on ImageNet.", "owner": "torchvision", "location": "", "license": "BSD-3-Clause", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.74},
    {"name": "ResNet50", "version": "1.0", "description": "Pre-trained ResNet50 from torchvision.", "owner": "torchvision", "location": "", "license": "BSD-3-Clause", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.76},
    {"name": "YOLO", "version": "9e", "description": "A convolutional neural network model for object detection.", "owner": "Ultralytics", "location": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov9e.pt", "license": "AGPL-3.0 License", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.85},
    {"name": "MegaDetector", "version": "5a-osa", "description": "OSA fine-tuned MegaDetector v5a.", "owner": "ICICLE", "location": "", "license": "MIT", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.92},
    {"name": "MegaDetector", "version": "6b-yolov9c", "description": "YOLOv9c backbone for better speed-accuracy.", "owner": "Microsoft AI for Earth", "location": "", "license": "MIT", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.90},
    {"name": "YOLO11L SoftToy", "version": "yolo11l_ep1_bs32_lr0.005", "description": "YOLOv11-large fine-tuned for soft toy detection.", "owner": "skhuvis", "location": "", "license": "AGPL-3.0 License", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.82},
    {"name": "YOLO", "version": "26n", "description": "A convolutional neural network model for object detection.", "owner": "Ultralytics", "location": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt", "license": "AGPL-3.0 License", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.85},
    {"name": "YOLO", "version": "26x", "description": "Extra-large YOLO26 for maximum accuracy.", "owner": "Ultralytics", "location": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26x.pt", "license": "AGPL-3.0 License", "framework": "PyTorch", "model_type": "convolutional neural network", "test_accuracy": 0.88},
]

# ── Datasheets: 5 public + 5 private; model_card_id optional (2 without) ─────
# identifier 8 and 9 have model_card_id = None to show standalone datasheets
DATASHEETS = [
    {"creator": "wqiu", "title": "LILA Camera Traps", "publisher": "LILA BC", "publication_year": 2021, "resource_type": "images", "size": "3 TB", "format": "jpeg", "version": "1.0", "rights": "public", "description": "Labelled camera-trap images from LILA BC.", "geo_location": "global", "category": "wildlife", "is_private": False, "model_card_id": 2},
    {"creator": "jstubbs", "title": "ImageNet-1K", "publisher": "Stanford / Princeton", "publication_year": 2012, "resource_type": "images", "size": "150 GB", "format": "jpeg", "version": "1.0", "rights": "academic", "description": "1000-class subset of the ImageNet dataset.", "geo_location": "global", "category": "classification", "is_private": False, "model_card_id": 3},
    {"creator": "nkarthikeyan", "title": "MNIST", "publisher": "NYU", "publication_year": 1998, "resource_type": "images", "size": "50 MB", "format": "idx", "version": "1.0", "rights": "public", "description": "Handwritten digit images 0-9.", "geo_location": "global", "category": "classification", "is_private": False, "model_card_id": 1},
    {"creator": "skhuvis", "title": "MS COCO 2017", "publisher": "cocodataset.org", "publication_year": 2017, "resource_type": "images", "size": "25 GB", "format": "jpeg", "version": "2017", "rights": "CC BY 4.0", "description": "Common Objects in Context detection/segmentation dataset.", "geo_location": "global", "category": "detection", "is_private": False, "model_card_id": 5},
    {"creator": "cgarcia", "title": "ImageNet ResNet Subset", "publisher": "Stanford / Princeton", "publication_year": 2015, "resource_type": "images", "size": "12 GB", "format": "jpeg", "version": "1.0", "rights": "academic", "description": "Curated ImageNet subset for ResNet50 benchmarking.", "geo_location": "global", "category": "classification", "is_private": False, "model_card_id": 4},
    {"creator": "rcardone", "title": "OSA Camera Traps", "publisher": "Open Science Alliance", "publication_year": 2024, "resource_type": "images", "size": "18 GB", "format": "jpeg", "version": "1.0", "rights": "research-only", "description": "OSA partner camera-trap imagery for fine-tuning.", "geo_location": "US", "category": "wildlife", "is_private": True, "model_card_id": 6},
    {"creator": "wqiu", "title": "ENA Wildlife Survey", "publisher": "ICICLE", "publication_year": 2024, "resource_type": "images", "size": "32 GB", "format": "jpeg", "version": "1.0", "rights": "research-only", "description": "Endangered North American species camera-trap survey.", "geo_location": "US", "category": "wildlife", "is_private": True, "model_card_id": 7},
    {"creator": "skhuvis", "title": "Soft Toy Inventory Frames", "publisher": "Internal", "publication_year": 2025, "resource_type": "images", "size": "2 GB", "format": "jpeg", "version": "1.0", "rights": "internal", "description": "Camera frames labelled with soft-toy bounding boxes.", "geo_location": "US", "category": "detection", "is_private": True, "model_card_id": None},
    {"creator": "skhuvis", "title": "YOLO26 Edge Benchmark", "publisher": "Ultralytics", "publication_year": 2025, "resource_type": "images", "size": "8 GB", "format": "jpeg", "version": "1.0", "rights": "internal", "description": "Edge device evaluation images for YOLO26n benchmarking.", "geo_location": "global", "category": "detection", "is_private": True, "model_card_id": None},
    {"creator": "skhuvis", "title": "YOLO26x High-Res Evaluation", "publisher": "Ultralytics", "publication_year": 2025, "resource_type": "images", "size": "45 GB", "format": "png", "version": "1.0", "rights": "internal", "description": "High-resolution evaluation set for YOLO26x accuracy testing.", "geo_location": "global", "category": "detection", "is_private": True, "model_card_id": 10},
]

NUM_USERS = 6
NUM_EDGE_DEVICES = 3


async def seed():
    dsn = DATABASE_URL.replace(":5432", ":443").split("?")[0]
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    conn = await asyncpg.connect(dsn, ssl=ctx, timeout=30)
    print("Connected.")

    async with conn.transaction():
        truncate_tables = [
            "experiment_images",
            "experiments",
            "raw_images",
            "datasheet_funding_references",
            "datasheet_geo_locations",
            "datasheet_descriptions",
            "datasheet_rights",
            "datasheet_related_identifiers",
            "datasheet_alternate_identifiers",
            "datasheet_dates",
            "datasheet_contributors",
            "datasheet_subjects",
            "datasheet_titles",
            "datasheet_creators",
            "datasheets",
            "models",
            "publishers",
            "model_cards",
            "dataset_schemas",
            "edge_devices",
            "users",
        ]
        for t in truncate_tables:
            await conn.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
        print("Truncated all tables.")

        for _ in range(NUM_USERS):
            await conn.execute(
                "INSERT INTO users (created_at, updated_at) VALUES ($1, $2)",
                _NOW,
                _NOW,
            )
        print(f"Inserted {NUM_USERS} users.")

        for _ in range(NUM_EDGE_DEVICES):
            await conn.execute(
                "INSERT INTO edge_devices (created_at, updated_at) VALUES ($1, $2)",
                _NOW,
                _NOW,
            )
        print(f"Inserted {NUM_EDGE_DEVICES} edge devices.")

        for mc in MODEL_CARDS:
            await conn.execute(
                """INSERT INTO model_cards (
                    name, version, is_private,
                    short_description, full_description,
                    keywords, author, citation,
                    input_data, input_type, output_data,
                    foundational_model, category, documentation,
                    created_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'',$14,$15)""",
                mc["name"],
                mc["version"],
                mc["is_private"],
                mc["short_description"],
                mc["full_description"],
                mc["keywords"],
                mc["author"],
                mc["citation"],
                mc["input_data"],
                mc["input_type"],
                mc["output_data"],
                mc.get("foundational_model", ""),
                mc.get("category", ""),
                _NOW,
                _NOW,
            )
        print(f"Inserted {len(MODEL_CARDS)} model cards.")

        for i, m in enumerate(MODELS):
            model_card_id = i + 1
            await conn.execute(
                """INSERT INTO models (
                    name, version, description, owner, location,
                    license, framework, model_type, test_accuracy,
                    model_card_id, created_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                m["name"],
                m["version"],
                m["description"],
                m["owner"],
                m["location"],
                m["license"],
                m["framework"],
                m["model_type"],
                m["test_accuracy"],
                model_card_id,
                _NOW,
                _NOW,
            )
        print(f"Inserted {len(MODELS)} models.")

        for ds in DATASHEETS:
            publisher_id = await conn.fetchval(
                "INSERT INTO publishers (name) VALUES ($1) RETURNING id",
                ds["publisher"],
            )

            datasheet_id = await conn.fetchval(
                """INSERT INTO datasheets (
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
                    model_card_id,
                    publisher_id
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,'pending',$8,$9,$10,$11)
                RETURNING identifier
                """,
                ds["publication_year"],
                ds["resource_type"],
                "Dataset",
                ds["size"],
                ds["format"],
                ds["version"],
                ds["is_private"],
                _NOW,
                _NOW,
                ds["model_card_id"],
                publisher_id,
            )

            await conn.execute(
                """INSERT INTO datasheet_creators (
                    datasheet_id, creator_name
                ) VALUES ($1,$2)""",
                datasheet_id,
                ds["creator"],
            )

            await conn.execute(
                """INSERT INTO datasheet_titles (
                    datasheet_id, title
                ) VALUES ($1,$2)""",
                datasheet_id,
                ds["title"],
            )

            if ds.get("category"):
                await conn.execute(
                    """INSERT INTO datasheet_subjects (
                        datasheet_id, subject
                    ) VALUES ($1,$2)""",
                    datasheet_id,
                    ds["category"],
                )

            if ds.get("rights"):
                await conn.execute(
                    """INSERT INTO datasheet_rights (
                        datasheet_id, rights
                    ) VALUES ($1,$2)""",
                    datasheet_id,
                    ds["rights"],
                )

            if ds.get("description"):
                await conn.execute(
                    """INSERT INTO datasheet_descriptions (
                        datasheet_id, description, description_type
                    ) VALUES ($1,$2,'Abstract')""",
                    datasheet_id,
                    ds["description"],
                )

            if ds.get("geo_location"):
                await conn.execute(
                    """INSERT INTO datasheet_geo_locations (
                        datasheet_id, geo_location_place
                    ) VALUES ($1,$2)""",
                    datasheet_id,
                    ds["geo_location"],
                )
        print(f"Inserted {len(DATASHEETS)} datasheets.")

    await conn.close()
    print("Done – 10 model cards, 10 models, 10 datasheets (5 public / 5 private; 2 datasheets without model_card_id).")


if __name__ == "__main__":
    asyncio.run(seed())
