from fastapi import APIRouter

from deepquest.web.deps import UserDep
from deepquest.web.schemas import MeOut

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/me")
async def me(user: UserDep) -> MeOut:
    return MeOut.of(user)
