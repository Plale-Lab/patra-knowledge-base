from fastapi import APIRouter, Depends, HTTPException, Request

from rest_server.deps import AssetIngestPrincipal, require_asset_ingest_principal
from rest_server.errors import not_found, upstream_fetch_failed
from rest_server.features.hf_import.models import HFImportFields, HFImportRequest
from rest_server.features.hf_import.service import (
    HuggingFaceGatedOrPrivateError,
    HuggingFaceRepoNotFoundError,
    HuggingFaceUpstreamError,
    InvalidHuggingFaceUrlError,
    import_from_huggingface,
)

router = APIRouter(prefix="/v1/hf-import", tags=["hf-import"])


@router.post("/preview", response_model=HFImportFields, response_model_exclude_none=True)
async def preview_hf_import(
    payload: HFImportRequest,
    request: Request,
    principal: AssetIngestPrincipal = Depends(require_asset_ingest_principal),
):
    """Fetch a public Hugging Face model/dataset repo and return flat fields
    matching the Submit form's reactive state. Never persists anything —
    the caller is expected to review/edit before creating the record."""
    request_tapis_token = (request.headers.get("X-Tapis-Token") or "").strip() or None
    try:
        return await import_from_huggingface(payload.url, payload.asset_type, request_tapis_token)
    except InvalidHuggingFaceUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HuggingFaceRepoNotFoundError as exc:
        raise not_found(str(exc) or "Hugging Face repo")
    except HuggingFaceGatedOrPrivateError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HuggingFaceUpstreamError as exc:
        raise upstream_fetch_failed("Hugging Face", str(exc))
