from fastapi import APIRouter

router = APIRouter()


@router.get("/overview")
def get_market_overview() -> dict[str, object]:
    return {
        "market_regime": "unknown",
        "emotion_score": None,
        "strong_sectors": [],
        "message": "Market overview will be generated after data ingestion is implemented.",
    }
