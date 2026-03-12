import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


SAFE_DYNAMIC_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,127}$")
SAFE_REQUIREMENT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*==.+$")
PrimitiveValue = str | int | float | bool | None


def _validate_dynamic_keys(mapping: dict[str, PrimitiveValue], field_name: str) -> dict[str, PrimitiveValue]:
    for key in mapping.keys():
        if not SAFE_DYNAMIC_KEY.fullmatch(key):
            raise ValueError(f"{field_name} contains an unsafe key: {key}")
    return mapping


class AssetAIModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None
    description: str | None = None
    owner: str | None = None
    location: str | None = None
    license: str | None = None
    framework: str | None = None
    model_type: str | None = None
    test_accuracy: float | None = None
    model_metrics: dict[str, PrimitiveValue] = Field(default_factory=dict)
    inference_labels: list[str] = Field(default_factory=list)
    model_structure: dict[str, Any] | list[Any] | None = None

    @field_validator("model_metrics")
    @classmethod
    def validate_model_metrics(cls, value: dict[str, PrimitiveValue]) -> dict[str, PrimitiveValue]:
        return _validate_dynamic_keys(value, "model_metrics")


class AssetModelCardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None
    short_description: str | None = None
    full_description: str | None = None
    keywords: str | None = None
    author: str | None = None
    citation: str | None = None
    input_data: str | None = None
    input_type: str | None = None
    output_data: str | None = None
    foundational_model: str | None = None
    category: str | None = None
    documentation: str | None = None
    is_private: bool = False
    is_gated: bool = False
    ai_model: AssetAIModelCreate | None = None
    bias_analysis: dict[str, PrimitiveValue] = Field(default_factory=dict)
    xai_analysis: dict[str, PrimitiveValue] = Field(default_factory=dict)
    model_requirements: list[str] = Field(default_factory=list)

    @field_validator("bias_analysis", "xai_analysis")
    @classmethod
    def validate_analysis_keys(cls, value: dict[str, PrimitiveValue]) -> dict[str, PrimitiveValue]:
        return _validate_dynamic_keys(value, "analysis")

    @field_validator("model_requirements")
    @classmethod
    def validate_model_requirements(cls, value: list[str]) -> list[str]:
        for requirement in value:
            if not SAFE_REQUIREMENT_KEY.fullmatch(requirement):
                raise ValueError(f"Unsafe model requirement entry: {requirement}")
        return value


class AssetPublisherCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    publisher_identifier: str | None = None
    publisher_identifier_scheme: str | None = None
    scheme_uri: str | None = None
    lang: str | None = None


class AssetDatasheetCreatorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_name: str
    name_type: str | None = None
    lang: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    name_identifier: str | None = None
    name_identifier_scheme: str | None = None
    name_id_scheme_uri: str | None = None
    affiliation: str | None = None
    affiliation_identifier: str | None = None
    affiliation_identifier_scheme: str | None = None
    affiliation_scheme_uri: str | None = None


class AssetDatasheetTitleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    title_type: str | None = None
    lang: str | None = None


class AssetDatasheetSubjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    subject_scheme: str | None = None
    scheme_uri: str | None = None
    value_uri: str | None = None
    classification_code: str | None = None
    lang: str | None = None


class AssetDatasheetContributorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contributor_type: str
    contributor_name: str
    name_type: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    name_identifier: str | None = None
    name_identifier_scheme: str | None = None
    name_id_scheme_uri: str | None = None
    affiliation: str | None = None
    affiliation_identifier: str | None = None
    affiliation_identifier_scheme: str | None = None
    affiliation_scheme_uri: str | None = None


class AssetDatasheetDateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    date_type: str
    date_information: str | None = None


class AssetDatasheetAlternateIdentifierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alternate_identifier: str
    alternate_identifier_type: str


class AssetDatasheetRelatedIdentifierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    related_identifier: str
    related_identifier_type: str
    relation_type: str
    related_metadata_scheme: str | None = None
    scheme_uri: str | None = None
    scheme_type: str | None = None
    resource_type_general: str | None = None


class AssetDatasheetRightsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rights: str | None = None
    rights_uri: str | None = None
    rights_identifier: str | None = None
    rights_identifier_scheme: str | None = None
    scheme_uri: str | None = None
    lang: str | None = None


class AssetDatasheetDescriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    description_type: str
    lang: str | None = None


class AssetDatasheetGeoLocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geo_location_place: str | None = None
    point_longitude: float | None = None
    point_latitude: float | None = None
    box_west: float | None = None
    box_east: float | None = None
    box_south: float | None = None
    box_north: float | None = None
    polygon: dict[str, Any] | None = None


class AssetDatasheetFundingReferenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    funder_name: str
    funder_identifier: str | None = None
    funder_identifier_type: str | None = None
    scheme_uri: str | None = None
    award_number: str | None = None
    award_uri: str | None = None
    award_title: str | None = None


class AssetDatasheetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_year: int | None = None
    resource_type: str | None = None
    resource_type_general: str | None = None
    size: str | None = None
    format: str | None = None
    version: str | None = None
    is_private: bool = False
    dataset_schema_id: int | None = None
    publisher: AssetPublisherCreate | None = None
    creators: list[AssetDatasheetCreatorCreate] = Field(default_factory=list)
    titles: list[AssetDatasheetTitleCreate] = Field(default_factory=list)
    subjects: list[AssetDatasheetSubjectCreate] = Field(default_factory=list)
    contributors: list[AssetDatasheetContributorCreate] = Field(default_factory=list)
    dates: list[AssetDatasheetDateCreate] = Field(default_factory=list)
    alternate_identifiers: list[AssetDatasheetAlternateIdentifierCreate] = Field(default_factory=list)
    related_identifiers: list[AssetDatasheetRelatedIdentifierCreate] = Field(default_factory=list)
    rights_list: list[AssetDatasheetRightsCreate] = Field(default_factory=list)
    descriptions: list[AssetDatasheetDescriptionCreate] = Field(default_factory=list)
    geo_locations: list[AssetDatasheetGeoLocationCreate] = Field(default_factory=list)
    funding_references: list[AssetDatasheetFundingReferenceCreate] = Field(default_factory=list)


class AssetBulkModelCardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[AssetModelCardCreate] = Field(min_length=1, max_length=25)


class AssetBulkDatasheetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[AssetDatasheetCreate] = Field(min_length=1, max_length=25)


class AssetIngestResult(BaseModel):
    asset_type: str
    asset_id: int
    organization: str
    created: bool
    duplicate: bool = False


class AssetBulkItemResult(BaseModel):
    index: int
    asset_type: str
    created: bool
    duplicate: bool = False
    asset_id: int | None = None
    error: str | None = None


class AssetBulkIngestResult(BaseModel):
    asset_type: str
    organization: str
    total: int
    created: int
    duplicates: int
    failed: int
    results: list[AssetBulkItemResult]
