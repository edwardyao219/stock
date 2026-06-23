from fastapi import APIRouter

from services.engine.rules.seed_rules import MVP_RULES

router = APIRouter()


@router.get("")
def list_rules() -> list[dict[str, object]]:
    return [rule.model_dump() for rule in MVP_RULES]
