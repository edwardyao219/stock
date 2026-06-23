from dataclasses import dataclass


@dataclass(frozen=True)
class MechanicalReview:
    report_date: str
    title: str
    content_md: str


def generate_daily_mechanical_review(report_date: str) -> MechanicalReview:
    content = "\n".join(
        [
            "# 每日机械复盘",
            "",
            "数据采集、特征计算、规则回归和交易计划模块仍在开发中。",
            "",
            "## 今日状态",
            "",
            "- 市场状态: unknown",
            "- 强势板块: 暂无",
            "- 规则表现: 暂无",
            "- 明日计划: 暂无",
        ]
    )
    return MechanicalReview(
        report_date=report_date,
        title=f"{report_date} 每日机械复盘",
        content_md=content,
    )
