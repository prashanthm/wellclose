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
        self._zip_cache: dict[str, tuple[bytes, dict]] = {}   # one download per bulk key/process

    def discover(self, well_selector: dict) -> Iterable[DocumentRef]:
        """{'all_bulk': True} | {'bulk': 'borehole'} | {'bulk_exploded': 'ewell_apm'} (one ref
        per zip member, flows through normal acquire/put_raw) | {'api12': '...'} (search page)."""
        if well_selector.get("all_bulk"):
            for key, path in self.cfg["bulk_datasets"].items():
                yield DocumentRef(self.name, self.cfg["base"] + path, doc_hint=f"bulk:{key}")
            return
        if bulk := well_selector.get("bulk"):
            yield DocumentRef(self.name, self.cfg["base"] + self.cfg["bulk_datasets"][bulk],
                              doc_hint=f"bulk:{bulk}")
            return
        if key := well_selector.get("bulk_exploded"):
            url = self.cfg["base"] + self.cfg["bulk_datasets"][key]
            data, _ = self._bulk_zip(key, url)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in z.namelist():
                    if not name.endswith("/"):
                        yield DocumentRef(self.name, f"{url}#member={name}",
                                          doc_hint=f"bulk:{key}/{name}",
                                          meta={"bulk": key, "member": name})
            return
        if api12 := well_selector.get("api12"):
            yield DocumentRef(self.name, self.cfg["base"] + self.cfg["document_search"] + f"?api={api12}",
                              well_hint=api12, doc_hint="record_search_page")

    def _bulk_zip(self, key: str, url: str) -> tuple[bytes, dict]:
        if key not in self._zip_cache:
            r = self.client.get(url)
            self._zip_cache[key] = (r.content, fetch_meta(r))
        return self._zip_cache[key]

    def fetch(self, ref: DocumentRef) -> tuple[bytes, dict]:
        if member := ref.meta.get("member"):
            data, meta = self._bulk_zip(ref.meta["bulk"], ref.url.split("#", 1)[0])
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return z.read(member), {**meta, "bulk_member": member, "url": ref.url}
        r = self.client.get(ref.url)
        return r.content, fetch_meta(r)

    @staticmethod
    def explode_bulk_zip(data: bytes) -> list[tuple[str, bytes]]:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return [(n, z.read(n)) for n in z.namelist() if not n.endswith("/")]
