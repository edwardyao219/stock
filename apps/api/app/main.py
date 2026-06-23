from fastapi import FastAPI

from apps.api.app.routers import health, market, parameter_recommendations, rules, trade_plans
from services.shared.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(health.router)
    app.include_router(market.router, prefix="/market", tags=["market"])
    app.include_router(
        parameter_recommendations.router,
        prefix="/parameter-recommendations",
        tags=["parameter-recommendations"],
    )
    app.include_router(rules.router, prefix="/rules", tags=["rules"])
    app.include_router(trade_plans.router, prefix="/trade-plans", tags=["trade-plans"])
    return app


app = create_app()
