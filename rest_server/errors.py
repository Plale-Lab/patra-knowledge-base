from fastapi import HTTPException


ASSET_NOT_AVAILABLE_DETAIL = "assets not avaible or not visible."


def asset_not_available_or_visible() -> HTTPException:
    return HTTPException(status_code=404, detail=ASSET_NOT_AVAILABLE_DETAIL)
