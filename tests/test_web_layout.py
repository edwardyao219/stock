import re
from pathlib import Path

WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def _css() -> str:
    return (WEB_SRC / "styles.css").read_text(encoding="utf-8")


def test_workspace_shell_allows_document_scroll() -> None:
    css = _css()

    assert re.search(
        r"body\s*\{[^}]*overflow:\s*auto;[^}]*overflow-x:\s*hidden;",
        css,
        re.S,
    )
    assert ".app-shell {" in css and "overflow: visible;" in css
    assert ".page-panel {" in css
    page_panel_rules = re.findall(r"\.page-panel\s*\{([^}]*)\}", css)
    assert page_panel_rules
    page_panel_rule = next(rule for rule in page_panel_rules if "flex: 1;" in rule)
    assert "overflow-y: auto;" in page_panel_rule
