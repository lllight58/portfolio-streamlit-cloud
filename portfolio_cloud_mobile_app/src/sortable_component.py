from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components


BUILD_DIR = Path(__file__).resolve().parent / "vendor" / "sortable_frontend"
_sortable_component = components.declare_component(
    "portfolio_sortable_items",
    path=str(BUILD_DIR),
)


def sort_items(
    items: list[str],
    direction: str = "vertical",
    custom_style: str | None = None,
    key: str | None = None,
) -> list[str]:
    if not BUILD_DIR.exists():
        raise FileNotFoundError("드래그 순서 컴포넌트 파일이 없습니다.")
    containers = [{"header": None, "items": items}]
    value = _sortable_component(
        items=containers,
        direction=direction,
        customStyle=custom_style,
        default=containers,
        key=key,
    )
    if not value or not isinstance(value, list):
        return items
    return list(value[0].get("items", items))
