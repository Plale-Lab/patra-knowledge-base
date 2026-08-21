"""Pydantic request/response models for the Hugging Face import feature.

The response is intentionally a single FLAT model whose field names match
the frontend's `mcForm`/`dsForm` reactive keys exactly (see
patra-frontend/app/src/views/SubmitView.vue), not the nested
AssetModelCardCreate/AssetDatasheetCreate creation payload shape. This lets
the frontend do `Object.assign(activeForm.value, result)` with zero
reshaping. The route uses `response_model_exclude_none=True` so fields we
couldn't derive are simply absent from the JSON, never sent as null.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HFImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    asset_type: Literal["model_card", "datasheet"]


class HFImportFields(BaseModel):
    """Union of mcForm + dsForm keys we can realistically fill from Hugging Face.

    Only one "half" of these will ever be populated for a given request
    (model_card fields vs. datasheet fields); `license` is shared by both
    forms and has the same meaning in either case.
    """

    # ---- model_card (mcForm) fields ----
    name: str | None = None
    author: str | None = None
    framework: str | None = None
    keywords: str | None = None
    documentation: str | None = None
    location: str | None = None
    short_description: str | None = None
    full_description: str | None = None
    is_gated: bool | None = None
    category: str | None = None
    input_type: str | None = None
    model_type: str | None = None
    foundational_model: str | None = None
    input_data: str | None = None
    citation: str | None = None

    # ---- datasheet (dsForm) fields ----
    title: str | None = None
    creator: str | None = None
    download_url: str | None = None
    description: str | None = None
    subjects: str | None = None
    publisher: str | None = None
    publication_year: int | None = None
    license_uri: str | None = None

    # ---- shared ----
    license: str | None = None
