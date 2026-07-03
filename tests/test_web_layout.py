import re
from pathlib import Path

WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def _css() -> str:
    return (WEB_SRC / "styles.css").read_text(encoding="utf-8")


def test_sector_page_panel_can_scroll_when_app_shell_locks_body_scroll() -> None:
    css = _css()

    assert "body {\n  margin: 0;\n  min-width: 320px;\n  overflow: hidden;\n}" in css
    assert ".app-shell {" in css and "overflow: hidden;" in css
    assert ".page-panel {" in css
    page_panel_rules = re.findall(r"\.page-panel\s*\{([^}]*)\}", css)
    assert page_panel_rules
    page_panel_rule = next(rule for rule in page_panel_rules if "flex: 1;" in rule)
    assert "overflow-y: auto;" in page_panel_rule
