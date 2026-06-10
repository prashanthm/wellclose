"""Texas RRC source (Brief §4.2): wellbore/completions queries + imaged records. Constants: sources.yaml."""
from __future__ import annotations
from typing import Iterable
from .base import DocumentRef, PoliteClient, fetch_meta, source_config


class TXRRCSource:
    name = "txrrc"

    def __init__(self) -> None:
        self.cfg = source_config()["txrrc"]
        self.client = PoliteClient(self.cfg["base"], self.cfg.get("rate_limit_rps"))
        self.img_client = PoliteClient(self.cfg["imaged_records"], self.cfg.get("rate_limit_rps"))

    def discover(self, well_selector: dict) -> Iterable[DocumentRef]:
        """{'orphan_list': True} | {'document_url': ...} | {'api8': '...'} (wellbore query page)."""
        if well_selector.get("orphan_list"):
            yield DocumentRef(self.name, self.cfg["orphan_list_csv"], doc_hint="orphan_list")
            return
        if url := well_selector.get("document_url"):
            yield DocumentRef(self.name, url, well_hint=well_selector.get("api8"))
            return
        if api8 := well_selector.get("api8"):
            q = f"{self.cfg['base']}{self.cfg['wellbore_query']}?searchArgs.apiNoHndlr.inputValue={api8}"
            yield DocumentRef(self.name, q, well_hint=api8, doc_hint="wellbore_query_page")

    def fetch(self, ref: DocumentRef) -> tuple[bytes, dict]:
        client = self.img_client if ref.url.startswith(self.cfg["imaged_records"]) else self.client
        r = client.get(ref.url)
        return r.content, fetch_meta(r)
