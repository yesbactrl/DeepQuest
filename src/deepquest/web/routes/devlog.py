"""История разработки DeepQuest из git — для страницы «Разработка»."""

from fastapi import APIRouter

from deepquest.config import PROJECT_ROOT
from deepquest.services import devlog
from deepquest.web.schemas import DevlogOut

router = APIRouter(prefix="/api/devlog", tags=["devlog"])


@router.get("")
async def get_devlog() -> DevlogOut:
    return DevlogOut.model_validate(await devlog.load(PROJECT_ROOT))
