from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ToolStatus = Literal["ok", "rejected"]


class SchemaPoolItem(BaseModel):
    dataset_id: str
    title: str
    source_family: str
    source_url: str
    public_access: str
    task_tags: dict[str, Any] = Field(default_factory=dict)


class PaperSchemaSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_url: str | None = None
    document_text: str | None = None
    document_format: str | None = Field(default=None, max_length=20)
    top_k: int = Field(default=5, ge=1, le=20)
    disable_llm: bool = True
    api_base: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    cache_dir: str | None = None


class ExtractionIssueModel(BaseModel):
    row_label: str
    reason: str


class ExtractedFieldModel(BaseModel):
    source_name: str
    canonical_name: str
    json_type: str
    description: str
    series_kind: str = "scalar"
    confidence: str = "high"
    aliases: list[str] = Field(default_factory=list)


class ExtractionResultModel(BaseModel):
    confidence: str
    rejected: bool
    rejection_reason: str = ""
    source_kind: str = ""
    grouped_fields: list[ExtractedFieldModel] = Field(default_factory=list)
    unresolved_fields: list[ExtractionIssueModel] = Field(default_factory=list)
    grouped_schema: dict[str, Any] = Field(default_factory=dict)
    machine_schema: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list)


class SearchCandidateModel(BaseModel):
    rank: int
    dataset_id: str
    title: str
    source_family: str
    source_url: str
    public_access: str
    score: float
    summary: str
    matched_field_groups: list[str] = Field(default_factory=list)
    derivable_field_groups: list[str] = Field(default_factory=list)
    missing_field_groups: list[str] = Field(default_factory=list)
    aligned_pairs: list[dict[str, Any]] = Field(default_factory=list)
    derived_support: list[dict[str, Any]] = Field(default_factory=list)
    type_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)


class PaperSchemaSearchResponse(BaseModel):
    status: ToolStatus
    message: str
    query_schema: dict[str, Any] = Field(default_factory=dict)
    extraction: ExtractionResultModel
    candidate_count: int = 0
    winner_dataset_id: str | None = None
    ranking: list[SearchCandidateModel] = Field(default_factory=list)


class MissingColumnAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_schema: dict[str, Any]
    candidate_dataset_id: str = Field(min_length=1)
    cache_dir: str | None = None


class DerivationDecisionModel(BaseModel):
    target_field: str
    status: Literal[
        "directly available",
        "derivable with provenance",
        "not safely derivable",
    ]
    rationale: str
    source_fields: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class MissingColumnAnalysisResponse(BaseModel):
    status: ToolStatus
    message: str
    dataset_id: str
    title: str
    source_family: str
    source_url: str
    summary: dict[str, Any]
    rows: list[DerivationDecisionModel]


PlannerMode = Literal["llm", "deterministic_fallback", "deterministic"]


class GeneratedFieldPlan(BaseModel):
    target_field: str
    mode: Literal["direct_copy", "extract_year", "monthly_aggregate"]
    source_fields: list[str] = Field(default_factory=list)
    date_field: str | None = None
    value_field: str | None = None
    aggregate: Literal["max", "min", "sum", "mean", "identity"] | None = None
    months: list[int] = Field(default_factory=list)
    output_kind: Literal["scalar", "json_array"] = "scalar"
    notes: str = ""


class SynthesisPlanModel(BaseModel):
    planner_mode: PlannerMode
    group_by_fields: list[str] = Field(default_factory=list)
    direct_fields: list[GeneratedFieldPlan] = Field(default_factory=list)
    derived_fields: list[GeneratedFieldPlan] = Field(default_factory=list)
    rejected_fields: list[str] = Field(default_factory=list)
    planner_notes: list[str] = Field(default_factory=list)


class GeneratedArtifactSummary(BaseModel):
    artifact_key: str
    title: str
    source_dataset_id: str
    planner_mode: PlannerMode
    row_count: int
    generated_fields: list[str] = Field(default_factory=list)
    rejected_fields: list[str] = Field(default_factory=list)
    output_csv_download_url: str
    output_schema_download_url: str
    review_submission_id: str | None = None


class SynthesizeDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_schema: dict[str, Any]
    candidate_dataset_id: str = Field(min_length=1)
    selected_fields: list[str] | None = None
    use_llm_plan: bool = True
    submitted_by: str | None = None
    api_base: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    cache_dir: str | None = None


class ValidationIssueModel(BaseModel):
    field: str
    severity: Literal["info", "warning", "error"]
    message: str


class SynthesizeDatasetResponse(BaseModel):
    status: ToolStatus
    message: str
    artifact: GeneratedArtifactSummary
    plan: SynthesisPlanModel
    validation_issues: list[ValidationIssueModel] = Field(default_factory=list)
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)


class SubmitGeneratedArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submitted_by: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class SubmitGeneratedArtifactResponse(BaseModel):
    status: ToolStatus
    message: str
    artifact_key: str
    submission_id: str
