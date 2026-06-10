"""Corpus manifest builder + acquisition driver (Brief §4, TASKS T2.7).

Selection criteria implemented:
- §4.1 GoM (BSEE borehole bulk): inactive Gulf wells, era-stratified (pre/post-1990 spud),
  >=min_pa with completed P&A (status PA — the gold anchors), >=min_decom_ops operators from
  the active-decommissioning set, per-operator cap for diversity.
- §4.2 TX (RRC orphan inventory): district-stratified orphan wells, bucketed by P-5 inactivity
  months as the era proxy. NOTE deviation from brief: the CMPL completions search host
  publishes robots.txt Disallow:/ so it is not crawled; all 200 TX wells come from the
  orphan inventory (>=30 required — exceeded by design). True era strata are validated
  from acquired document dates post-pull.
- §4.3 Volve: local subset (well report PDFs) under data/volve, license-gated.

The manifest is W2-compatible: [{well_id, source, selector, meta}]."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import logging
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BULK_CACHE = Path("data/bulk")
MANIFEST_PATH = Path("data/corpus_manifest.json")
STATE_PATH = Path("data/corpus_state.json")

# Shelf decommissioning-active operators (§4.1 "demo relevance"); matched as substrings.
DECOM_OPERATORS = ["Fieldwood", "W & T Offshore", "Chevron", "Apache", "Arena Offshore",
                   "GOM Shelf", "Talos", "Cox Operating", "Energy Transfer"]

INACTIVE_STATUSES = {"PA", "TA"}     # permanently / temporarily abandoned (§4.1 "inactive")


# ---------- bulk data ----------

def fetch_bulk_cached(key: str, max_age_days: float = 30) -> Path:
    """Download a BSEE bulk zip once into data/bulk/ (re-used by selection + spike)."""
    from .sources.volve import get_source
    BULK_CACHE.mkdir(parents=True, exist_ok=True)
    out = BULK_CACHE / f"{key}.zip"
    if out.exists() and (time.time() - out.stat().st_mtime) < max_age_days * 86400:
        return out
    src = get_source("bsee")
    refs = list(src.discover({"bulk": key}))
    data, _ = src.fetch(refs[0])
    out.write_bytes(data)
    return out


def load_boreholes(zip_path: Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith(".txt"))
        text = z.read(name).decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _spud_year(row: dict) -> int | None:
    d = (row.get("WELL_SPUD_DATE") or "").strip()
    try:
        return int(d.split("/")[-1]) if "/" in d else None
    except ValueError:
        return None


def select_gom_wells(rows: list[dict], n: int = 50, min_pa: int = 10,
                     min_decom_ops: int = 3, per_operator_cap: int = 6) -> list[dict]:
    """§4.1: era-stratified inactive Gulf wells; PA wells anchor the gold set."""
    candidates = [r for r in rows
                  if r.get("REGION_CODE") == "G"
                  and r.get("BOREHOLE_STAT_CD") in INACTIVE_STATUSES
                  and _spud_year(r)]
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in candidates:
        era = "pre-1990" if _spud_year(r) < 1990 else "post-1990"   # type: ignore[operator]
        strata[(era, r["BOREHOLE_STAT_CD"])].append(r)
    for group in strata.values():    # deterministic, spread across operators
        group.sort(key=lambda r: (r["COMPANY_NAME"], r["API_WELL_NUMBER"]))

    picked: list[dict] = []
    op_count: dict[str, int] = defaultdict(int)

    def take(era: str, status: str, count: int, prefer_ops: list[str] | None = None) -> None:
        pool = strata.get((era, status), [])
        for r in pool:
            if len([p for p in picked if p["_era"] == era and p["BOREHOLE_STAT_CD"] == status]) >= count:
                break
            op = r["COMPANY_NAME"]
            if r in picked or op_count[op] >= per_operator_cap:
                continue
            if prefer_ops and not any(d.lower() in op.lower() for d in prefer_ops):
                continue
            r["_era"] = era
            picked.append(r)
            op_count[op] += 1

    half = n // 2
    pa_each = max(min_pa // 2, 3)
    for era in ("pre-1990", "post-1990"):
        take(era, "PA", pa_each, prefer_ops=DECOM_OPERATORS)   # gold anchors from decom operators
        take(era, "PA", pa_each)                                # fill if preferred ran short
        take(era, "TA", half - pa_each)                         # inactive needing dossiers
        take(era, "PA", half)                                   # top-up era to half
    # top-up to n regardless of strata if anything ran short; relax the operator cap
    # last (diversity preferred, target count guaranteed when candidates exist)
    for cap in (per_operator_cap, None):
        for (era, _), pool in sorted(strata.items()):
            for r in pool:
                if len(picked) >= n:
                    break
                if r not in picked and (cap is None or op_count[r["COMPANY_NAME"]] < cap):
                    r["_era"] = era
                    picked.append(r)
                    op_count[r["COMPANY_NAME"]] += 1

    decom_present = {d for d in DECOM_OPERATORS
                     for p in picked if d.lower() in p["COMPANY_NAME"].lower()}
    pa_n = sum(1 for p in picked if p["BOREHOLE_STAT_CD"] == "PA")
    if pa_n < min_pa or len(decom_present) < min_decom_ops:
        log.warning("GoM selection constraints not fully met: PA=%d (need %d), decom_ops=%d (need %d)",
                    pa_n, min_pa, len(decom_present), min_decom_ops)
    return [{"api12": p["API_WELL_NUMBER"], "well_name": p["WELL_NAME"].strip(),
             "operator": p["COMPANY_NAME"], "status": p["BOREHOLE_STAT_CD"],
             "spud": p["WELL_SPUD_DATE"], "stratum": p["_era"],
             "lease": p.get("BOTM_LEASE_NUMBER"), "area_block":
                 f"{p.get('BOTM_AREA_CODE','').strip()} {p.get('BOTM_BLOCK_NUMBER','').strip()}".strip()}
            for p in picked[:n]]


# ---------- TXRRC orphan inventory ----------

def fetch_orphan_wells() -> list[dict]:
    """Scrape orphan page -> monthly zip -> xlsx rows (cached in data/bulk)."""
    import openpyxl
    from .sources.volve import get_source
    BULK_CACHE.mkdir(parents=True, exist_ok=True)
    src = get_source("txrrc")
    url = src.orphan_zip_url()
    cache = BULK_CACHE / url.rsplit("/", 1)[-1]
    if not cache.exists():
        data, _ = src.fetch(next(iter(src.discover({"orphan_list": True}))))
        cache.write_bytes(data)
    with zipfile.ZipFile(cache) as z:
        xlsx = next(n for n in z.namelist() if n.endswith(".xlsx"))
        wb = openpyxl.load_workbook(io.BytesIO(z.read(xlsx)), read_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(h).strip().upper() for h in next(rows_iter)]
    out = []
    for vals in rows_iter:
        row = dict(zip(header, ["" if v is None else str(v).strip() for v in vals]))
        if row.get("API"):
            out.append(row)
    return out


def select_tx_wells(orphans: list[dict], n: int = 200, max_per_district: int | None = None) -> list[dict]:
    """§4.2 (adapted, see module docstring): district round-robin over the orphan inventory,
    bucketed by P-5 inactivity months (oldest-inactive first within each district)."""
    by_district: dict[str, list[dict]] = defaultdict(list)
    for r in orphans:
        by_district[r.get("DISTRICT_NAME", "")].append(r)
    for d in by_district.values():       # longest-inactive first = oldest paper trail
        d.sort(key=lambda r: -int(r.get("CALC_MONTHS_P5_INACT") or 0))
    districts = sorted(by_district, key=lambda d: -len(by_district[d]))
    cap = max_per_district or max(1, n // max(len(districts) // 2, 1))
    picked: list[dict] = []
    idx = {d: 0 for d in districts}
    while len(picked) < n:
        progressed = False
        for d in districts:
            if len(picked) >= n:
                break
            pool = by_district[d]
            if idx[d] < len(pool) and sum(1 for p in picked if p["DISTRICT_NAME"] == d) < cap:
                picked.append(pool[idx[d]])
                idx[d] += 1
                progressed = True
        if not progressed:
            break
    def bucket(months: str) -> str:
        m = int(months or 0)
        return "inact>=20y" if m >= 240 else ("inact>=5y" if m >= 60 else "inact<5y")
    return [{"api8": p["API"], "district": p["DISTRICT_NAME"], "lease_id": p.get("LEASE_ID"),
             "operator": p.get("OPERATOR_NAME"), "lease_name": p.get("LEASE_NAME"),
             "county": p.get("COUNTY_NAME"), "well_no": (p.get("WELL_NO") or "").strip(),
             "stratum": bucket(p.get("CALC_MONTHS_P5_INACT", "0")), "status": "orphan"}
            for p in picked[:n]]


# ---------- manifest ----------

def build_manifest(out: Path = MANIFEST_PATH, gom: int = 50, tx: int = 200,
                   volve: bool = True, spike: bool = False) -> dict:
    if spike:
        gom, tx = 5, 5
    entries: list[dict] = []
    # BSEE corpus-level structured bulk (always; cheap and idempotent)
    for key in ("borehole", "apd", "ewell_apd", "ewell_apm", "ewell_eor", "ewell_war",
                "decom_cost", "scanned_docs_index"):
        entries.append({"well_id": None, "source": "bsee",
                        "selector": {"bulk_exploded": key} if not spike or key == "borehole"
                        else {"bulk": key},
                        "meta": {"kind": "bulk", "dataset": key}})
    gom_wells = select_gom_wells(load_boreholes(fetch_bulk_cached("borehole")), n=gom)
    for w in gom_wells:
        entries.append({"well_id": None, "source": "bsee",
                        "selector": {"api12": w["api12"]},
                        "meta": {"kind": "well", "jurisdiction": "BSEE", **w}})
    tx_wells = select_tx_wells(fetch_orphan_wells(), n=tx)
    for w in tx_wells:
        entries.append({"well_id": None, "source": "txrrc",
                        "selector": {"well_documents": w["api8"], "district": w["district"],
                                     "lease_number": w["lease_id"]},
                        "meta": {"kind": "well", "jurisdiction": "TXRRC",
                                 "api": f"42{w['api8']}00", **w}})
    if volve:
        entries.append({"well_id": None, "source": "volve", "selector": {"glob": "**/*.pdf"},
                        "meta": {"kind": "well_set", "jurisdiction": "NO"}})
    manifest = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "spike": spike, "counts": {"gom": len(gom_wells), "tx": len(tx_wells)},
                "entries": entries}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1))
    log.info("manifest: %d entries (%d GoM wells, %d TX wells) -> %s",
             len(entries), len(gom_wells), len(tx_wells), out)
    return manifest


# ---------- acquisition driver ----------

def _entry_key(e: dict) -> str:
    return hashlib.sha1(f"{e['source']}:{json.dumps(e['selector'], sort_keys=True)}".encode()).hexdigest()


def acquire_manifest(manifest_path: Path = MANIFEST_PATH, source: str | None = None,
                     limit: int | None = None, state_path: Path = STATE_PATH) -> dict:
    """Walk the manifest through pipeline.acquire with resume + HTTP-level never-re-fetch."""
    from .pipeline.acquire import acquire, ensure_well
    manifest = json.loads(Path(manifest_path).read_text())
    state: dict[str, Any] = json.loads(state_path.read_text()) if state_path.exists() else {}
    report: dict[str, dict] = defaultdict(lambda: {"done": 0, "skipped": 0, "failed": 0, "docs": 0})
    entries = [e for e in manifest["entries"] if not source or e["source"] == source]
    if limit:
        entries = entries[:limit]
    for i, e in enumerate(entries, 1):
        key, src, meta = _entry_key(e), e["source"], e.get("meta", {})
        tag = meta.get("api") or meta.get("api12") or meta.get("dataset") or src
        if state.get(key, {}).get("status") == "done":
            report[src]["skipped"] += 1
            continue
        try:
            well_id = None
            if meta.get("kind") == "well":
                well_id = ensure_well(api_number=meta.get("api") or meta.get("api12"),
                                      jurisdiction=meta.get("jurisdiction", "TXRRC"),
                                      name=meta.get("well_name") or meta.get("lease_name"))
            doc_ids = acquire(src, e["selector"], well_id)
            state[key] = {"status": "done", "docs": len(doc_ids), "well_id": well_id,
                          "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            report[src]["done"] += 1
            report[src]["docs"] += len(doc_ids)
            print(f"[{src} {i}/{len(entries)}] {tag} docs={len(doc_ids)}")
        except Exception as exc:  # noqa: BLE001 — one well must not kill the batch (§6.3)
            state[key] = {"status": "failed", "error": str(exc)[:500]}
            report[src]["failed"] += 1
            log.warning("acquire failed for %s %s: %s", src, tag, exc)
            print(f"[{src} {i}/{len(entries)}] {tag} FAILED: {str(exc)[:120]}")
        finally:
            state_path.write_text(json.dumps(state, indent=0))
    return {k: dict(v) for k, v in report.items()}


def corpus_status(manifest_path: Path = MANIFEST_PATH, state_path: Path = STATE_PATH) -> dict:
    from sqlalchemy import func, select
    from .db import session
    from .models import Document
    manifest = json.loads(Path(manifest_path).read_text())
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    per_source: dict[str, dict] = defaultdict(lambda: {"entries": 0, "done": 0, "failed": 0, "pending": 0})
    strata: dict[str, int] = defaultdict(int)
    for e in manifest["entries"]:
        s = per_source[e["source"]]
        s["entries"] += 1
        st = state.get(_entry_key(e), {}).get("status")
        s["done" if st == "done" else ("failed" if st == "failed" else "pending")] += 1
        if stratum := e.get("meta", {}).get("stratum"):
            strata[f"{e['source']}:{stratum}"] += 1
    with session() as s_:
        db_counts = dict(s_.execute(
            select(Document.source, func.count()).group_by(Document.source)).all())
        total, distinct = s_.execute(select(func.count(Document.document_id),
                                            func.count(Document.document_id.distinct()))).one()
    return {"sources": {k: dict(v) for k, v in per_source.items()},
            "strata": dict(strata), "documents_in_db": db_counts,
            "dedupe_ok": bool(total == distinct), "built_at": manifest.get("built_at")}


def verify_endpoints() -> dict:
    """T2.6 ritual: probe every configured URL; on bulk failure, diff against the live catalog."""
    import httpx
    from .config import settings
    from .sources.base import source_config
    cfg = source_config()
    results: dict[str, str] = {}
    client = httpx.Client(headers={"User-Agent": settings().user_agent},
                          timeout=30, follow_redirects=True)
    def probe(name: str, url: str) -> None:
        try:
            r = client.get(url, headers={"Range": "bytes=0-256"})
            results[name] = f"{r.status_code} {url}"
        except Exception as exc:  # noqa: BLE001
            results[name] = f"ERROR {url} ({exc})"
    for key, path in cfg["bsee"]["bulk_datasets"].items():
        probe(f"bsee.{key}", cfg["bsee"]["base"] + path)
    probe("bsee.catalog", cfg["bsee"]["base"] + cfg["bsee"]["raw_data_catalog"])
    t = cfg["txrrc"]
    probe("txrrc.imaged_records", t["imaged_records"].split("/esd3-rrc")[0]
          + f"/search-profile?profileId={17}")
    probe("txrrc.orphan_page", t["orphan_page"])
    ok = all(v.split(" ")[0] in ("200", "206") for v in results.values())
    # EWA (webapps2) is unused by acquisition; its TLS chain is incomplete for Python's CA
    # bundle (works in browsers/curl via Keychain). Probe informationally, never gate on it.
    probe("txrrc.wellbore_query[info-only]", t["ewa_base"] + t["wellbore_query"])
    probe("txrrc.orphan_query[info-only]", t["ewa_base"] + t["orphan_query"])
    return {"ok": ok, "probes": results}
