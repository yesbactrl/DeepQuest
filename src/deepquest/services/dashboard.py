"""Набор графиков на дашборде."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import DashboardWidget, User
from deepquest.services.charts import Bucket, ChartConfig, ChartType, Metric, Period, Size, Split

MAX_WIDGETS = 12

DEFAULT_WIDGETS = [
    ChartConfig(
        title="Фокус по дням",
        metric=Metric.MINUTES,
        bucket=Bucket.DAY,
        split=Split.GOAL,
        period=Period.MONTH,
        chart=ChartType.BAR,
        size=Size.FULL,
    ),
    ChartConfig(
        title="Время по целям",
        metric=Metric.MINUTES,
        split=Split.GOAL,
        period=Period.MONTH,
        chart=ChartType.PIE,
        size=Size.HALF,
    ),
    ChartConfig(
        title="XP по неделям",
        metric=Metric.XP,
        bucket=Bucket.WEEK,
        split=Split.GOAL,
        period=Period.QUARTER,
        chart=ChartType.LINE,
        size=Size.HALF,
    ),
]


async def list_widgets(session: AsyncSession, user: User) -> list[DashboardWidget]:
    if not user.dashboard_seeded:
        # Первый заход: кладём графики по умолчанию. Дальше набор — целиком твой.
        await replace_widgets(session, user, DEFAULT_WIDGETS)
    widgets = await session.scalars(
        select(DashboardWidget)
        .where(DashboardWidget.user_id == user.id)
        .order_by(DashboardWidget.position)
    )
    return list(widgets)


async def replace_widgets(session: AsyncSession, user: User, configs: list[ChartConfig]) -> None:
    if len(configs) > MAX_WIDGETS:
        raise ValueError(f"No more than {MAX_WIDGETS} widgets")
    await session.execute(delete(DashboardWidget).where(DashboardWidget.user_id == user.id))
    session.add_all(
        DashboardWidget(user_id=user.id, position=i, config=config.model_dump(mode="json"))
        for i, config in enumerate(configs)
    )
    user.dashboard_seeded = True
    await session.flush()


def widget_config(widget: DashboardWidget) -> ChartConfig:
    return ChartConfig.model_validate(widget.config)
