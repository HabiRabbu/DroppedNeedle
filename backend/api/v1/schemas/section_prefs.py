from typing import Literal

from infrastructure.msgspec_fastapi import AppStruct


class SectionPrefItem(AppStruct):
    key: str
    title: str
    description: str
    zone: str
    enabled: bool = True
    available: bool = True
    requires: str | None = None


class SectionPrefsResponse(AppStruct):
    pages: dict[str, list[SectionPrefItem]] = {}


class SectionPrefUpdateItem(AppStruct):
    key: str
    enabled: bool


class SectionPrefsUpdate(AppStruct):
    page: Literal["home", "discover", "sidebar"]
    sections: list[SectionPrefUpdateItem] = []
