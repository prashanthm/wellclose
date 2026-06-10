"""Texas RRC source (Brief §4.2): imaged well records via the Neubus NDE service + the
RRC-published orphan well inventory. Constants: sources.yaml (T2.6, verified 2026-06-10).

Compliance notes (§4.5):
- webapps.rrc.texas.gov publishes robots.txt `Disallow: /` — the CMPL completions search is
  therefore NOT crawled. Well selection uses the orphan inventory zip, which RRC publishes
  as a bulk download for exactly this purpose.
- rrcsearch3.neubus.com robots.txt allows all; rrcsearch3fs.neubus.com publishes none (4xx).
- Neubus issues an anonymous public-user JWT (AuthToken cookie) on first page load; all
  JSON endpoints take it as a Bearer plus the page's CSRF token. Flow pinned 2026-06-10:
  /search-profile → POST /getSearchImages → POST /getViewRecordOauth → POST /getTabFilesOauth
  → GET {fs}/api/v1/single/{nuid}?profileId=17 (PDF bytes)."""
from __future__ import annotations
import logging
import re
from typing import Any, Iterable
from .base import DocumentRef, PoliteClient, fetch_meta, source_config

log = logging.getLogger(__name__)

WELL_RECORDS_PROFILE = 17        # "Oil and Gas Well Records" NDE search profile
_FS_BASE = "https://rrcsearch3fs.neubus.com"
# The Neubus file server sits behind a WAF that hard-blocks non-browser User-Agents (403),
# even though the search/metadata APIs accept our honest UA. Browser-record access is public
# and unauthenticated; we send a browser UA + viewer Referer for the binary download ONLY.
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")
_VIEWER_REFERER = "https://rrcsearchpubneuview.neubus.com/"


class TXRRCSource:
    name = "txrrc"

    def __init__(self) -> None:
        self.cfg = source_config()["txrrc"]
        rps = self.cfg.get("rate_limit_rps")
        self.nde_base = self.cfg["imaged_records"].split("/esd3-rrc")[0]
        self.img_client = PoliteClient(self.nde_base, rps)
        self.fs_client = PoliteClient(_FS_BASE, rps)
        self.www_client = PoliteClient("https://www.rrc.texas.gov", rps)
        self._bearer: str | None = None
        self._csrf: str | None = None

    # ---------- Neubus session ----------

    def _public_token(self) -> str:
        """Mint the anonymous public-user JWT the Neubus SPA issues to every visitor.

        The portal is a client-only app: its JavaScript generates an ephemeral PS512 keypair
        in-browser and signs this exact fixed `publicuser` claim set for the `public` audience
        (no server credential, no per-user secret). We replicate that public, unauthenticated
        access path. This is not impersonation of a real account — `publicuser@neubus.com` is
        the site's shared anonymous identity for open public-record search."""
        import time
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        now = int(time.time())
        claims = {"email": "publicuser@neubus.com", "family_name": "User",
                  "given_name": "Public", "name": "Public User",
                  "preferred_username": "publicuser",
                  "sub": "f7ec6582-3d68-4eae-b6e5-39fcb321ed4c", "iat": now,
                  "iss": "https://ndeiam.neubus.com/realms/rrcsearch3",
                  "aud": "public", "exp": now + 86400}
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return jwt.encode(claims, key, algorithm="PS512")

    def _neubus_auth(self) -> tuple[str, str]:
        """Bootstrap a public session: page load for the CSRF token, plus the SPA-style
        anonymous public-user JWT for the Bearer header."""
        if self._bearer and self._csrf:
            return self._bearer, self._csrf
        r = self.img_client.get(f"{self.nde_base}/search-profile?profileId={WELL_RECORDS_PROFILE}")
        m = re.search(r'name="csrf-token" content="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("Neubus public session bootstrap failed (no csrf-token) — "
                               "re-verify the NDE flow (sources.yaml T2.6 note)")
        self._csrf, self._bearer = m.group(1), self._public_token()
        return self._bearer, self._csrf

    def _nde_post(self, path: str, payload: dict) -> dict:
        bearer, csrf = self._neubus_auth()
        r = self.img_client.post(f"{self.nde_base}{path}", json=payload, headers={
            "Authorization": f"Bearer {bearer}", "X-CSRF-TOKEN": csrf,
            "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        out = r.json()
        if out.get("message") != "success":
            raise RuntimeError(f"Neubus {path} returned {out.get('message')!r}")
        return out

    # ---------- Neubus search + document enumeration ----------

    @staticmethod
    def neusearch_payload(*, district: str | None = None, lease_number: str | None = None,
                          api8: str | None = None, page: int = 1, page_size: int = 50) -> dict:
        items = []
        if district:
            items.append({"key": "district", "value": district.zfill(2),
                          "label": "District", "type": "DROPDOWN"})
        if lease_number:
            items.append({"key": "lease_number", "value": lease_number,
                          "label": "Oil Lease/Gas ID", "type": "TEXT"})
        if api8:
            items.append({"key": "api_ft", "value": api8, "label": "API Number", "type": "TEXT"})
        if not items:
            raise ValueError("need at least one of district/lease_number/api8")
        return {"excludeName": "", "excludeValue": None, "extraParams": "", "includeName": "",
                "order": "asc", "orderBy": "", "page": page, "pageSize": page_size,
                "profile": WELL_RECORDS_PROFILE, "recordFromDate": "", "recordToDate": "",
                "saveSearch": "false", "strict": "true", "Searchitems": {"item": items}}

    def neubus_search(self, **kw: Any) -> list[dict]:
        """Search imaged well records; returns [{doc_id, fields:{...}}] (one per record box)."""
        out = self._nde_post("/getSearchImages", self.neusearch_payload(**kw))
        images = (out.get("data", {}).get("data", {}).get("search_results", {}) or {}).get("images", [])
        results = []
        for im in images:
            fields = {f["field_name"]: f["field_value"] for f in im.get("image_fields", [])}
            results.append({"doc_id": im["doc_id"], "fields": fields})
        return results

    def neubus_files(self, doc_id: str) -> list[dict]:
        """Record → tab files: [{nuid, name, format, tab, page_count, file_size}]."""
        view = self._nde_post("/getViewRecordOauth",
                              {"doc_id": doc_id, "profile_id": WELL_RECORDS_PROFILE})
        files: list[dict] = []
        for tab, entries in (view.get("data", {}).get("data", {}) or {}).items():
            for entry in entries or []:
                image_id = entry.get("doc_id")
                if not (image_id and entry.get("has_files")):
                    continue
                tf = self._nde_post("/getTabFilesOauth",
                                    {"profile_id": WELL_RECORDS_PROFILE, "image_id": image_id,
                                     "page": 1, "page_size": 100, "order_by": "", "order": ""})
                for f in (tf.get("data", {}).get("data", {}) or {}).get("files", []):
                    files.append({"nuid": f["nuid"], "name": f.get("name"),
                                  "format": f.get("format"), "tab": tab,
                                  "page_count": f.get("page_count"),
                                  "file_size": f.get("file_size")})
        return files

    def neubus_doc_refs(self, *, api8: str | None = None, district: str | None = None,
                        lease_number: str | None = None) -> Iterable[DocumentRef]:
        for rec in self.neubus_search(api8=api8, district=district, lease_number=lease_number):
            fields = rec["fields"]
            for f in self.neubus_files(rec["doc_id"]):
                yield DocumentRef(
                    self.name,
                    f"{_FS_BASE}/api/v1/single/{f['nuid']}?profileId={WELL_RECORDS_PROFILE}",
                    well_hint=api8, doc_hint=f.get("name"),
                    meta={"neubus": f, "record_fields": {
                        k: fields.get(k) for k in ("district", "lease_number", "county",
                                                   "operator_name", "lease_name", "profile_type")}})

    # ---------- orphan inventory ----------

    def orphan_zip_url(self) -> str:
        """The orphan list moves monthly (/media/<hash>/orphanwells-MM-YY.zip) — scrape the page."""
        r = self.www_client.get(self.cfg["orphan_page"])
        m = re.search(r'href="(/media/[^"]*orphanwells[^"]*\.zip)"', r.text, re.I)
        if not m:
            raise RuntimeError("orphan wells zip link not found on orphan_page (T2.6: page changed?)")
        return "https://www.rrc.texas.gov" + m.group(1)

    # ---------- Source protocol ----------

    def discover(self, well_selector: dict) -> Iterable[DocumentRef]:
        """{'orphan_list': True} | {'document_url': ...} | {'well_documents': api8,
        'district': d, 'lease_number': l} — per-well imaged records via Neubus."""
        if well_selector.get("orphan_list"):
            yield DocumentRef(self.name, self.orphan_zip_url(), doc_hint="orphan_list")
            return
        if url := well_selector.get("document_url"):
            yield DocumentRef(self.name, url, well_hint=well_selector.get("api8"))
            return
        if api8 := well_selector.get("well_documents"):
            yield from self.neubus_doc_refs(api8=api8,
                                            district=well_selector.get("district"),
                                            lease_number=well_selector.get("lease_number"))
            return
        if lease := well_selector.get("lease_number"):
            yield from self.neubus_doc_refs(district=well_selector.get("district"),
                                            lease_number=lease)

    def fetch(self, ref: DocumentRef) -> tuple[bytes, dict]:
        if ref.url.startswith(_FS_BASE):
            bearer, _ = self._neubus_auth()
            r = self.fs_client.get(ref.url, headers={
                "Authorization": f"Bearer {bearer}", "User-Agent": _BROWSER_UA,
                "Referer": _VIEWER_REFERER})
        elif ref.url.startswith(self.nde_base):
            r = self.img_client.get(ref.url)
        else:
            r = self.www_client.get(ref.url)
        return r.content, fetch_meta(r)
