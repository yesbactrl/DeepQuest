"""Сводка (уровень, сезон, норма, стрик) и настраиваемые графики."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from deepquest.services import charts, dashboard, summary
from deepquest.services.charts import ChartConfig
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import ChartDataOut, SummaryOut, WidgetOut

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/summary")
async def get_summary(session: SessionDep, user: UserDep) -> SummaryOut:
    return SummaryOut.of(await summary.build_summary(session, user, datetime.now(UTC)))


@router.get("/stats/series")
async def series(
    config: Annotated[ChartConfig, Query()], session: SessionDep, user: UserDep
) -> ChartDataOut:
    """Данные для графика по его настройкам — и для виджета, и для превью в редакторе."""
    return ChartDataOut.of(await charts.chart_data(session, user, config, datetime.now(UTC)))


async def _widgets_out(session: SessionDep, user: UserDep) -> list[WidgetOut]:
    return [
        WidgetOut(id=w.id, position=w.position, config=dashboard.widget_config(w))
        for w in await dashboard.list_widgets(session, user)
    ]


@router.get("/dashboard")
async def get_dashboard(session: SessionDep, user: UserDep) -> list[WidgetOut]:
    return await _widgets_out(session, user)


@router.put("/dashboard")
async def put_dashboard(
    configs: list[ChartConfig], session: SessionDep, user: UserDep
) -> list[WidgetOut]:
    """Набор графиков целиком: так проще и переставлять, и удалять."""
    try:
        await dashboard.replace_widgets(session, user, configs)
    except ValueError:
        raise HTTPException(422, f"Не больше {dashboard.MAX_WIDGETS} графиков.") from None
    return await _widgets_out(session, user)
