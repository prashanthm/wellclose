"""Volve local-path adapter (Brief §4.3) — licensed data, never fetched or redistributed by us."""
from __future__ import annotations
from pathlib import Path
from typing import Iterable
from .base import DocumentRef, source_config


class VolveSource:
    name = "volve"

    def __init__(self) -> None:
        self.root = Path(source_config()["volve"]["local_path"])

    def discover(self, well_selector: dict) -> Iterable[DocumentRef]:
        if not self.root.exists():
            raise FileNotFoundError(
                f"Volve path {self.root} not found. Download Volve under Equinor's license and set "
                "sources.yaml volve.local_path (record terms in data/LICENSES.md).")
        for p in self.root.glob(well_selector.get("glob", "**/*.pdf")):
            yield DocumentRef(self.name, p.as_uri(), well_hint=well_selector.get("uwi"),
                              meta={"path": str(p)})

    def fetch(self, ref: DocumentRef) -> tuple[bytes, dict]:
        p = Path(ref.meta["path"])
        return p.read_bytes(), {"fetched_at": "local", "url": ref.url, "headers": {}}


REGISTRY = {"bsee": "wellclose.sources.bsee:BSEESource",
            "txrrc": "wellclose.sources.txrrc:TXRRCSource",
            "volve": "wellclose.sources.volve:VolveSource"}


def get_source(name: str):
    import importlib
    mod, cls = REGISTRY[name].split(":")
    return getattr(importlib.import_module(mod), cls)()
