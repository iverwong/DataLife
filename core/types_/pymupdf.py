from dataclasses import dataclass


@dataclass
class TocEntry:
    lvl: int
    title: str
    page: int
