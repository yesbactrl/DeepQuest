from datetime import UTC, datetime

from fastapi import APIRouter

from deepquest.services import streak
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import MeOut, MeUpdate

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/me")
async def me(user: UserDep) -> MeOut:
    return MeOut.of(user)


@router.patch("/me")
async def update_me(body: MeUpdate, session: SessionDep, user: UserDep) -> MeOut:
    now = datetime.now(UTC)
    if body.streak_enabled is False:
        await streak.pause(session, user, now)
    elif body.streak_enabled is True:
        await streak.resume(session, user, now)
    return MeOut.of(user)
