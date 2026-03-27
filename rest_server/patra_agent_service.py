import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import asdict
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
import os


class AgentServiceError(RuntimeError):
    pass


DEFAULT_LLM_API_BASE = os.getenv("PATRA_AGENT_LLM_API_BASE", "http://127.0.0.1:1234/v1")
DEFAULT_LLM_MODEL = os.getenv("PATRA_AGENT_LLM_MODEL", "qwen/qwen3.5-9b")
DEFAULT_LLM_API_KEY = os.getenv("PATRA_AGENT_LLM_API_KEY", "lm-studio")


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell_chunks: list[str] | None = None
        self._inside_cell = False

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        if lowered == "table":
            self._current_table = []
        elif lowered == "tr" and self._current_table is not None:
            self._current_row = []
        elif lowered in {"td", "th"} and self._current_row is not None:
            self._inside_cell = True
            self._current_cell_chunks = []

    def handle_data(self, data: str) -> None:
        if self._inside_cell and self._current_cell_chunks is not None:
            self._current_cell_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"td", "th"} and self._current_row is not None and self._current_cell_chunks is not None:
            text = " ".join(part.strip() for part in self._current_cell_chunks if part.strip())
            self._current_row.append(" ".join(text.split()))
            self._inside_cell = False
            self._current_cell_chunks = None
        elif lowered == "tr" and self._current_table is not None and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif lowered == "table" and self._current_table is not None:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = None


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    candidates = [current.parent, *current.parents]
    for candidate in candidates:
        if (candidate / "src").exists():
            return candidate
    # Container fallback: rest_server is often mounted under /app.
    if len(current.parents) >= 2:
        return current.parents[1]
    return current.parent


def _default_cache_dir() -> Path:
    return _repo_root() / "PATRA" / ".patra-agent-cache"


def _ensure_source_path() -> None:
    repo_root = _repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _modules():
    _ensure_source_path()
    from src.hybrid_schema_matcher import HybridSchemaMatcher, LocalOpenAICompatibleLLM
    from src.missing_column_derivation import analyze_missing_columns, build_derivation_summary
    from src.paper_schema_parser import (
        SchemaExtractionResult,
        _extract_rows_from_table,
        _result_from_groups,
        extract_schema_from_document,
    )
    from src.patra_schema_pool import build_default_public_schema_pool

    return {
        "HybridSchemaMatcher": HybridSchemaMatcher,
        "LocalOpenAICompatibleLLM": LocalOpenAICompatibleLLM,
        "SchemaExtractionResult": SchemaExtractionResult,
        "_extract_rows_from_table": _extract_rows_from_table,
        "_result_from_groups": _result_from_groups,
        "analyze_missing_columns": analyze_missing_columns,
        "build_derivation_summary": build_derivation_summary,
        "build_default_public_schema_pool": build_default_public_schema_pool,
        "extract_schema_from_document": extract_schema_from_document,
    }


def _normalize_cache_dir(cache_dir: str | None) -> str:
    target = Path(cache_dir) if cache_dir else _default_cache_dir()
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def _looks_like_gen_parallel_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    for site in ("BW", "Theta", "Philly", "Helios"):
        if (path / site / "training_data").is_dir():
            return True
    return (path / "SDSC-95").is_dir()


def _gen_parallel_workloads_repo_path() -> str | None:
    """Local clone of DIR-LAB/Gen-Parallel-Workloads (optional extension to the public pool).

    Resolution order:
    1) ``GEN_PARALLEL_WORKLOADS_REPO`` environment variable
    2) ``<repo>/external/Gen-Parallel-Workloads``
    3) ``<repo>/Gen-Parallel-Workloads``
    4) ``<repo>/PATRA/.patra-agent-cache/Gen-Parallel-Workloads``
    """
    env = (os.getenv("GEN_PARALLEL_WORKLOADS_REPO") or "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser())
    root = _repo_root()
    candidates.extend(
        [
            root / "external" / "Gen-Parallel-Workloads",
            root / "Gen-Parallel-Workloads",
            root / "PATRA" / ".patra-agent-cache" / "Gen-Parallel-Workloads",
        ]
    )
    for candidate in candidates:
        if _looks_like_gen_parallel_repo(candidate):
            return str(candidate.resolve())
    return None


@lru_cache(maxsize=32)
def _load_pool(cache_dir: str, gen_parallel_repo_marker: str):
    """Load merged public + optional Gen-Parallel-Workloads pool (cached per cache dir + GPW path)."""
    gp = gen_parallel_repo_marker or None
    return _modules()["build_default_public_schema_pool"](
        cache_dir,
        gen_parallel_workloads_repo=gp,
    )


def _get_pool(cache_dir: str):
    normalized = _normalize_cache_dir(cache_dir)
    gp = _gen_parallel_workloads_repo_path() or ""
    return _load_pool(normalized, gp)


def _pair_map(cache_dir: str) -> dict[str, Any]:
    return {pair.dataset_id: pair for pair in _get_pool(cache_dir)}


def list_schema_pool(cache_dir: str | None = None) -> list[dict[str, Any]]:
    normalized_cache = _normalize_cache_dir(cache_dir)
    items = []
    for pair in _get_pool(normalized_cache):
        items.append(
            {
                "dataset_id": pair.dataset_id,
                "title": pair.title,
                "source_family": pair.source_family,
                "source_url": pair.source_url,
                "public_access": pair.public_access,
                "task_tags": pair.task_tags,
            }
        )
    return items


def _download_to_cache(url: str, cache_dir: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix or ".txt"
    safe_name = Path(parsed.path).name or f"download{suffix}"
    destination = Path(cache_dir) / "documents" / safe_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "PATRA Agent Tools"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())
    return destination


def _write_temp_document(document_text: str, document_format: str | None, cache_dir: str) -> Path:
    suffix = ".md"
    if document_format:
        lowered = document_format.lower().lstrip(".")
        suffix = f".{lowered}"
    elif document_text.lstrip().startswith("{"):
        suffix = ".json"
    temp_dir = Path(cache_dir) / "documents"
    temp_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=suffix,
        prefix="agent_query_",
        dir=temp_dir,
        delete=False,
    )
    try:
        handle.write(document_text)
    finally:
        handle.close()
    return Path(handle.name)


def _container_patra_root() -> Path | None:
    """Directory where the PATRA tree is mounted inside Docker (or override)."""
    override = os.getenv("PATRA_CONTAINER_PATRA_ROOT", "").strip()
    if override:
        p = Path(override)
        if p.is_dir():
            return p.resolve()
    candidate = Path("/app/PATRA")
    if candidate.is_dir():
        return candidate.resolve()
    return None


def _resolve_document_path(document_path: str) -> Path:
    """
    Resolve a server-side document path. Host paths like
    D:\\...\\PATRA\\input_documents\\x.docx are mapped to the container mount
    when the raw path does not exist (typical Docker + Windows dev).
    """
    raw = Path(document_path)
    if raw.exists():
        return raw.resolve()

    parts = [p for p in re.split(r"[\\/]+", document_path.strip()) if p and p not in (".",)]
    for i, part in enumerate(parts):
        if part.lower() != "patra" or i + 1 >= len(parts):
            continue
        rel_parts = parts[i + 1 :]
        if ".." in rel_parts:
            break
        root = _container_patra_root()
        if root is None:
            break
        candidate = (root.joinpath(*rel_parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            break
        if candidate.is_file():
            return candidate
        break

    return raw


def _extract_from_html_document(source: Path):
    modules = _modules()
    parser = _HtmlTableParser()
    parser.feed(source.read_text(encoding="utf-8", errors="ignore"))
    tables = parser.tables
    if not tables:
        result_type = modules["SchemaExtractionResult"]
        return result_type(
            grouped_schema={},
            machine_schema={},
            grouped_fields=[],
            provenance=[],
            unresolved_fields=[],
            confidence="reject",
            rejected=True,
            rejection_reason="No candidate schema table found in the HTML document.",
            source_kind="html",
        )
    best_table = max(tables, key=len)
    groups, issues = modules["_extract_rows_from_table"](best_table)
    title = f"PATRA query schema extracted from {source.name}"
    return modules["_result_from_groups"](groups, issues, "html", title)


def _extract_schema_from_source_path(source: Path) -> dict[str, Any]:
    suffix = source.suffix.lower()
    if suffix in {".html", ".htm"}:
        extraction = _extract_from_html_document(source)
    elif suffix == ".pdf":
        raise AgentServiceError("PDF parsing is not yet enabled for this PATRA tool. Please provide a DOCX, HTML, Markdown table, or JSON schema.")
    else:
        extraction = _modules()["extract_schema_from_document"](str(source))
    return extraction.to_dict()


def extract_schema(document_path: str | None, document_url: str | None, document_text: str | None, document_format: str | None, cache_dir: str | None) -> dict[str, Any]:
    normalized_cache = _normalize_cache_dir(cache_dir)
    provided = [bool(document_path), bool(document_url), bool(document_text and document_text.strip())]
    if sum(provided) != 1:
        raise AgentServiceError("Provide exactly one of document_path, document_url, or document_text.")

    if document_path:
        source = _resolve_document_path(document_path)
        if not source.exists():
            container_root = _container_patra_root()
            hint = ""
            if container_root is not None:
                hint = (
                    " If the API runs in Docker, you may use the container path "
                    f"(e.g. {container_root}/input_documents/...) "
                    "or your Windows repo path — PATRA maps .../PATRA/... under that mount when it exists."
                )
            raise AgentServiceError(f"Document path does not exist: {document_path}.{hint}")
    elif document_url:
        source = _download_to_cache(document_url, normalized_cache)
    else:
        source = _write_temp_document(document_text or "", document_format, normalized_cache)

    return _extract_schema_from_source_path(source)


def extract_schema_from_uploaded_file(
    file_bytes: bytes,
    filename: str | None,
    document_format: str | None,
) -> dict[str, Any]:
    safe_name = Path(filename or "uploaded_document").name
    suffix = Path(safe_name).suffix
    if document_format:
        suffix = f".{document_format.lower().lstrip('.')}"
    if not suffix:
        suffix = ".txt"

    with tempfile.TemporaryDirectory(prefix="patra-upload-") as temp_dir:
        temp_path = Path(temp_dir) / f"query_upload{suffix}"
        temp_path.write_bytes(file_bytes)
        return _extract_schema_from_source_path(temp_path)


def _build_matcher(cache_dir: str, disable_llm: bool, api_base: str | None, model: str | None, api_key: str | None, timeout_seconds: int):
    modules = _modules()
    llm_client = None
    resolved_api_base = api_base or DEFAULT_LLM_API_BASE
    resolved_model = model or DEFAULT_LLM_MODEL
    resolved_api_key = api_key or DEFAULT_LLM_API_KEY
    if not disable_llm and resolved_api_base and resolved_model:
        llm_client = modules["LocalOpenAICompatibleLLM"](
            api_base=resolved_api_base,
            model=resolved_model,
            api_key=resolved_api_key,
            timeout_seconds=timeout_seconds,
        )
    return modules["HybridSchemaMatcher"](
        schema_records=[pair.to_matcher_record() for pair in _get_pool(cache_dir)],
        llm_client=llm_client,
    )


def _candidate_rows(match_result: Any, cache_dir: str, query_schema: dict[str, Any]) -> list[dict[str, Any]]:
    modules = _modules()
    pair_lookup = _pair_map(cache_dir)
    rows: list[dict[str, Any]] = []
    for item in match_result["ranking"]:
        pair = pair_lookup[item["schema_id"]]
        decisions = modules["analyze_missing_columns"](query_schema, pair.schema, pair.raw_schema)
        derivation = modules["build_derivation_summary"](decisions)
        rows.append(
            {
                "rank": item["rank"],
                "dataset_id": pair.dataset_id,
                "title": pair.title,
                "source_family": pair.source_family,
                "source_url": pair.source_url,
                "public_access": pair.public_access,
                "score": item["overall_score"],
                "summary": item["summary"],
                "matched_field_groups": [
                    row["target_field"]
                    for row in derivation["rows"]
                    if row["status"] == "directly available"
                ],
                "derivable_field_groups": [
                    row["target_field"]
                    for row in derivation["rows"]
                    if row["status"] == "derivable with provenance"
                ],
                "missing_field_groups": [
                    row["target_field"]
                    for row in derivation["rows"]
                    if row["status"] == "not safely derivable"
                ],
                "aligned_pairs": item.get("aligned_pairs", []),
                "derived_support": item.get("derived_support", []),
                "type_conflicts": item.get("type_conflicts", []),
                "tradeoffs": item.get("tradeoffs", []),
            }
        )
    return rows


def run_paper_schema_search(
    document_path: str | None,
    document_url: str | None,
    document_text: str | None,
    document_format: str | None,
    top_k: int,
    disable_llm: bool,
    api_base: str | None,
    model: str | None,
    api_key: str | None,
    timeout_seconds: int,
    cache_dir: str | None,
) -> dict[str, Any]:
    normalized_cache = _normalize_cache_dir(cache_dir)
    extraction = extract_schema(document_path, document_url, document_text, document_format, normalized_cache)
    if extraction["rejected"]:
        return {
            "status": "rejected",
            "message": extraction["rejection_reason"] or "The document could not be parsed into a PATRA schema.",
            "query_schema": extraction["machine_schema"],
            "extraction": extraction,
            "candidate_count": 0,
            "winner_dataset_id": None,
            "ranking": [],
        }

    matcher = _build_matcher(normalized_cache, disable_llm, api_base, model, api_key, timeout_seconds)
    match_result = asdict(matcher.match_schema(extraction["machine_schema"], top_k=top_k))
    ranking = _candidate_rows(match_result["report"], normalized_cache, extraction["machine_schema"])
    winner = ranking[0]["dataset_id"] if ranking else None
    return {
        "status": "ok",
        "message": "Schema extracted and ranked against the PATRA public dataset-schema pool.",
        "query_schema": extraction["machine_schema"],
        "extraction": extraction,
        "candidate_count": len(ranking),
        "winner_dataset_id": winner,
        "ranking": ranking,
    }


def run_uploaded_paper_schema_search(
    file_bytes: bytes,
    filename: str | None,
    document_format: str | None,
    top_k: int,
    disable_llm: bool,
    api_base: str | None,
    model: str | None,
    api_key: str | None,
    timeout_seconds: int,
    cache_dir: str | None,
) -> dict[str, Any]:
    normalized_cache = _normalize_cache_dir(cache_dir)
    extraction = extract_schema_from_uploaded_file(file_bytes, filename, document_format)
    if extraction["rejected"]:
        return {
            "status": "rejected",
            "message": extraction["rejection_reason"] or "The uploaded document could not be parsed into a PATRA schema.",
            "query_schema": extraction["machine_schema"],
            "extraction": extraction,
            "candidate_count": 0,
            "winner_dataset_id": None,
            "ranking": [],
        }

    matcher = _build_matcher(normalized_cache, disable_llm, api_base, model, api_key, timeout_seconds)
    match_result = asdict(matcher.match_schema(extraction["machine_schema"], top_k=top_k))
    ranking = _candidate_rows(match_result["report"], normalized_cache, extraction["machine_schema"])
    winner = ranking[0]["dataset_id"] if ranking else None
    return {
        "status": "ok",
        "message": "Uploaded document parsed in-memory and ranked against the PATRA public dataset-schema pool.",
        "query_schema": extraction["machine_schema"],
        "extraction": extraction,
        "candidate_count": len(ranking),
        "winner_dataset_id": winner,
        "ranking": ranking,
    }
def analyze_missing_columns_for_candidate(query_schema: dict[str, Any], candidate_dataset_id: str, cache_dir: str | None) -> dict[str, Any]:
    normalized_cache = _normalize_cache_dir(cache_dir)
    lookup = _pair_map(normalized_cache)
    if candidate_dataset_id not in lookup:
        raise AgentServiceError(f"Unknown candidate dataset id: {candidate_dataset_id}")

    pair = lookup[candidate_dataset_id]
    modules = _modules()
    decisions = modules["analyze_missing_columns"](query_schema, pair.schema, pair.raw_schema)
    summary = modules["build_derivation_summary"](decisions)
    return {
        "status": "ok",
        "message": "Missing-column feasibility evaluated under strict deterministic derivation rules.",
        "dataset_id": pair.dataset_id,
        "title": pair.title,
        "source_family": pair.source_family,
        "source_url": pair.source_url,
        "summary": {
            "direct_count": summary["direct_count"],
            "derivable_count": summary["derivable_count"],
            "rejected_count": summary["rejected_count"],
        },
        "rows": summary["rows"],
    }
