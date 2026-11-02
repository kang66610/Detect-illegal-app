from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.app.schemas.apk import APKOut
from backend.app.services import apk_service

router = APIRouter(prefix="/api/apks", tags=["apk"])


@router.post("", response_model=APKOut)
def upload_apk(file: UploadFile = File(...)):
    return apk_service.save_apk(file)


@router.get("", response_model=list[APKOut])
def list_apks():
    return [_to_out(a) for a in apk_service.list_apks()]


@router.delete("/{apk_id}")
def delete_apk(apk_id: int):
    try:
        apk_service.delete_apk(apk_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _to_out(a) -> APKOut:
    out = APKOut.model_validate(a)
    out.has_policy = bool(a.policy_raw)
    return out
