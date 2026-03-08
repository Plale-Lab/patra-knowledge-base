from typing import Optional

from pydantic import BaseModel


# --- Model Cards (matches rest_server MCReconstructor output) ---


class ModelCardSummary(BaseModel):
    """List endpoint: mc_id, name, categories, author, version, short_description."""

    mc_id: int
    name: str
    categories: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    short_description: Optional[str] = None


class AIModel(BaseModel):
    """Nested model from models table. model_id is integer per schema."""

    model_id: int
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    location: Optional[str] = None
    license: Optional[str] = None
    framework: Optional[str] = None
    model_type: Optional[str] = None
    test_accuracy: Optional[float] = None


class ModelCardDetail(BaseModel):
    """Detail endpoint: matches reconstruct() format. external_id is integer per schema."""

    external_id: int
    name: str
    version: Optional[str] = None
    short_description: Optional[str] = None
    full_description: Optional[str] = None
    keywords: Optional[str] = None
    author: Optional[str] = None
    input_data: Optional[str] = None
    output_data: Optional[str] = None
    input_type: Optional[str] = None
    categories: Optional[str] = None
    citation: Optional[str] = None
    foundational_model: Optional[str] = None
    ai_model: Optional[AIModel] = None


# --- Datasheets (DataCite 4.5-style) ---


class DatasheetCreator(BaseModel):
    creator_name: str
    name_type: Optional[str] = None
    lang: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    name_identifier: Optional[str] = None
    name_identifier_scheme: Optional[str] = None
    name_id_scheme_uri: Optional[str] = None
    affiliation: Optional[str] = None
    affiliation_identifier: Optional[str] = None
    affiliation_identifier_scheme: Optional[str] = None
    affiliation_scheme_uri: Optional[str] = None


class DatasheetTitle(BaseModel):
    title: str
    title_type: Optional[str] = None
    lang: Optional[str] = None


class DatasheetPublisher(BaseModel):
    name: str
    publisher_identifier: Optional[str] = None
    publisher_identifier_scheme: Optional[str] = None
    scheme_uri: Optional[str] = None
    lang: Optional[str] = None


class DatasheetSubject(BaseModel):
    subject: str
    subject_scheme: Optional[str] = None
    scheme_uri: Optional[str] = None
    value_uri: Optional[str] = None
    classification_code: Optional[str] = None
    lang: Optional[str] = None


class DatasheetContributor(BaseModel):
    contributor_type: str
    contributor_name: str
    name_type: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    name_identifier: Optional[str] = None
    name_identifier_scheme: Optional[str] = None
    name_id_scheme_uri: Optional[str] = None
    affiliation: Optional[str] = None
    affiliation_identifier: Optional[str] = None
    affiliation_identifier_scheme: Optional[str] = None
    affiliation_scheme_uri: Optional[str] = None


class DatasheetDate(BaseModel):
    date: str
    date_type: str
    date_information: Optional[str] = None


class DatasheetAlternateIdentifier(BaseModel):
    alternate_identifier: str
    alternate_identifier_type: str


class DatasheetRelatedIdentifier(BaseModel):
    related_identifier: str
    related_identifier_type: str
    relation_type: str
    related_metadata_scheme: Optional[str] = None
    scheme_uri: Optional[str] = None
    scheme_type: Optional[str] = None
    resource_type_general: Optional[str] = None


class DatasheetRights(BaseModel):
    rights: Optional[str] = None
    rights_uri: Optional[str] = None
    rights_identifier: Optional[str] = None
    rights_identifier_scheme: Optional[str] = None
    scheme_uri: Optional[str] = None
    lang: Optional[str] = None


class DatasheetDescription(BaseModel):
    description: str
    description_type: str
    lang: Optional[str] = None


class DatasheetGeoLocation(BaseModel):
    geo_location_place: Optional[str] = None
    point_longitude: Optional[float] = None
    point_latitude: Optional[float] = None
    box_west: Optional[float] = None
    box_east: Optional[float] = None
    box_south: Optional[float] = None
    box_north: Optional[float] = None
    polygon: Optional[dict] = None


class DatasheetFundingReference(BaseModel):
    funder_name: str
    funder_identifier: Optional[str] = None
    funder_identifier_type: Optional[str] = None
    scheme_uri: Optional[str] = None
    award_number: Optional[str] = None
    award_uri: Optional[str] = None
    award_title: Optional[str] = None


class DatasheetSummary(BaseModel):
    """List endpoint."""

    identifier: int
    title: str
    creator: Optional[str] = None
    category: Optional[str] = None


class DatasheetDetail(BaseModel):
    """Detail endpoint: DataCite-style nested structure plus selected flat fields."""

    identifier: int
    publication_year: Optional[int] = None
    resource_type: Optional[str] = None
    resource_type_general: Optional[str] = None
    size: Optional[str] = None
    format: Optional[str] = None
    version: Optional[str] = None
    is_private: bool = False
    updated_at: Optional[str] = None
    model_card_id: Optional[int] = None
    dataset_schema_id: Optional[int] = None

    # Nested DataCite-style lists / objects
    creators: list[DatasheetCreator] = []
    titles: list[DatasheetTitle] = []
    publisher: Optional[DatasheetPublisher] = None
    subjects: list[DatasheetSubject] = []
    contributors: list[DatasheetContributor] = []
    dates: list[DatasheetDate] = []
    alternate_identifiers: list[DatasheetAlternateIdentifier] = []
    related_identifiers: list[DatasheetRelatedIdentifier] = []
    rights_list: list[DatasheetRights] = []
    descriptions: list[DatasheetDescription] = []
    geo_locations: list[DatasheetGeoLocation] = []
    funding_references: list[DatasheetFundingReference] = []
