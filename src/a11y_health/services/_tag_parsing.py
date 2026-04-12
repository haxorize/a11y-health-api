import re
from typing import Literal

_WCAG_VERSION_LEVEL = re.compile(r"^wcag2(1|2)?a{1,2}$")
_WCAG_CRITERION = re.compile(r"^wcag(\d)(\d)(\d+)$")
_CAT_TAG = re.compile(r"^cat\.(.+)$")
_VERSION_MAP: dict[str | None, str] = {None: "2.0", "1": "2.1", "2": "2.2"}

Classification = Literal[
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
    "wcag22a",
    "wcag22aa",
    "best-practice",
]


def parse_wcag_tag(tag: str) -> dict[str, str] | None:
    if tag == "best-practice":
        return {"standard": "best-practice"}
    m = _WCAG_VERSION_LEVEL.match(tag)
    if not m:
        return None
    version = _VERSION_MAP[m.group(1)]
    level = "AA" if tag.endswith("aa") else "A"
    return {"standard": "wcag", "version": version, "level": level}


def extract_classifications(tags: list[str]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for tag in tags:
        parsed = parse_wcag_tag(tag)
        if parsed is not None:
            results.append(parsed)
    return results


def extract_wcag_criteria(tags: list[str]) -> list[str]:
    results: list[str] = []
    for tag in tags:
        m = _WCAG_CRITERION.match(tag)
        if m:
            results.append(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
    return results


def extract_category(tags: list[str]) -> str | None:
    for tag in tags:
        m = _CAT_TAG.match(tag)
        if m:
            return m.group(1)
    return None
