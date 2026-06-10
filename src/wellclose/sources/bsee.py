"""BSEE/BOEM GoM source (Brief §4.1): bulk datasets + per-document fetch. Constants: sources.yaml (T2.6)."""
from __future__ import annotations
import io
import zipfile
from typing import Iterable
from .base import DocumentRef, PoliteClient, fetch_meta, source_config


class BSEESource:
    name = "bsee"

    def __init__(self) -> None:
        self.cfg = source_config()["bsee"]
        self.client = PoliteClient(self.cfg["base"], self.cfg.get("rate_limit_rps"))

    def discover(self, well_selector: dict) -> Iterable[DocumentRef]:
        """{'all_bulk': True} | {'bulk': 'borehole'} | {'api12': '...'} (record search page)."""
        if well_selector.get("all_bulk"):
            for key, path in self.cfg["bulk_datasets"].items():
                yield DocumentRef(self.name, self.cfg["base"] + path, doc_hint=f"bulk:{key}")
            return
        if bulk := well_selector.get("bulk"):
            yield DocumentRef(self.name, self.cfg["base"] + self.cfg["bulk_datasets"][bulk],
                              doc_hint=f"bulk:{bulk}")
            return
        if api12 := well_selector.get("api12"):
            yield DocumentRef(self.name, self.cfg["base"] + self.cfg["document_search"] + f"?api={api12}",
                              well_hint=api12, doc_hint="record_search_page")

    def fetch(self, ref: DocumentRef) -> tuple[bytes, dict]:
        r = self.client.get(ref.url)
        return r.content, fetch_meta(r)

    @staticmethod
    def explode_bulk_zip(data: bytes) -> list[tuple[str, bytes]]:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return [(n, z.read(n)) for n in z.namelist() if not n.endswith("/")]
