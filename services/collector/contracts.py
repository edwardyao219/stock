from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionResult:
    source: str
    dataset: str
    trade_date: str
    rows: int
    status: str
    message: str = ""
