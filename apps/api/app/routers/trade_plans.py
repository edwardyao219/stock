from fastapi import APIRouter

router = APIRouter()


@router.get("/latest")
def get_latest_trade_plans() -> dict[str, object]:
    return {
        "plan_date": None,
        "trade_date": None,
        "plans": [],
        "message": "Trade plans will appear after rule execution is implemented.",
    }
