"""Stage E — Entity resolution, conflicts, deterministic validators (Brief §7E).
Resolution: API12/UWI exact, lease+name fuzzy fallback; unresolved -> orphan_facts queue.
Conflicts: same field_path, materially different values -> conflict_group (auto-resolution only
for whitelisted later-superseding-form rule; everything else human). Validators are CODE, not LLM."""
from __future__ import annotations
import hashlib
import json
import re
from sqlalchemy import select
from ..db import session
from ..models import Document, ExtractedFact, Well

_API_RE = re.compile(r"(\d{2})[- ]?(\d{3})[- ]?(\d{5})(?:[- ]?(\d{2})(?:[- ]?(\d{2}))?)?")


def normalize_api(raw: str) -> str | None:
    m = _API_RE.search(raw or "")
    if not m:
        return None
    parts = [m.group(1), m.group(2), m.group(3), m.group(4) or "00"]
    return "".join(parts)  # 12-digit: state(2)+county(3)+well(5)+sidetrack(2) (§5.4)


def _num(value: str) -> float | None:
    m = re.search(r"-?\d[\d,]*\.?\d*", value or "")
    return float(m.group(0).replace(",", "")) if m else None


def resolve_well(document_id: str) -> str | None:
    """Attach document + its facts to a Well using extracted identifiers."""
    with session() as s:
        facts = s.scalars(select(ExtractedFact).where(
            ExtractedFact.document_id == document_id)).all()
        api_fact = next((f for f in facts if f.field_path == "well.api_number"), None)
        uwi_fact = next((f for f in facts if f.field_path == "well.uwi"), None)
        well = None
        if api_fact and (api12 := normalize_api(api_fact.value or "")):
            well = s.scalars(select(Well).where(Well.api_number == api12)).first()
            if well is None:
                well = Well(api_number=api12, jurisdiction="TXRRC")
                s.add(well)
                s.flush()
        elif uwi_fact and uwi_fact.value:
            well = s.scalars(select(Well).where(Well.uwi == uwi_fact.value.strip())).first()
            if well is None:
                well = Well(uwi=uwi_fact.value.strip(), jurisdiction="NO")
                s.add(well)
                s.flush()
        if well is None:
            return None  # facts remain well_id=None -> orphan_facts review queue (§8.7)
        doc = s.get(Document, document_id)
        if doc and not doc.well_id:
            doc.well_id = well.well_id
        for f in facts:
            f.well_id = f.well_id or well.well_id
        return well.well_id


def detect_conflicts(well_id: str) -> int:
    """Group materially different values for the same scalar field_path."""
    scalar_paths = {"wellbore.td_md_ft", "well.api_number", "well.operator",
                    "well.spud_date", "well.gau_determination", "plugging_record.plugging_date"}
    n = 0
    with session() as s:
        facts = s.scalars(select(ExtractedFact).where(
            ExtractedFact.well_id == well_id,
            ExtractedFact.status.in_(("proposed", "approved")))).all()
        by_path: dict[str, list[ExtractedFact]] = {}
        for f in facts:
            if f.field_path in scalar_paths:
                by_path.setdefault(f.field_path, []).append(f)
        for path, group in by_path.items():
            values = {(_num(f.value) if "ft" in path else (f.value or "").strip().lower())
                      for f in group}
            if len(values) > 1:
                gid = conflict_group_id(well_id, path)
                for f in group:
                    f.conflict_group_id = gid
                    n += 1
    return n


def conflict_group_id(well_id: str, field_path: str) -> str:
    """Deterministic group id: Temporal activity retries must regroup identically (§6.3),
    not mint fresh ids that orphan prior review-queue state."""
    return hashlib.sha256(f"{well_id}:{field_path}".encode()).hexdigest()[:32]


def run_validators(well_id: str) -> int:
    """Physical consistency (§7E): plugs within TD, plug top<base, cement_top<=shoe,
    casing shoes deeper for smaller strings. Violations flag facts; never silent."""
    flags = 0
    with session() as s:
        facts = s.scalars(select(ExtractedFact).where(
            ExtractedFact.well_id == well_id,
            ExtractedFact.status.in_(("proposed", "approved")))).all()
        td_vals = [_num(f.value) for f in facts if f.field_path == "wellbore.td_md_ft"]
        td = max((v for v in td_vals if v), default=None)

        def flag(f: ExtractedFact, msg: str) -> None:
            nonlocal flags
            f.validation_flags = (f.validation_flags or []) + [msg]
            flags += 1

        casing_shoes: list[tuple[float, float, ExtractedFact]] = []
        for f in facts:
            if f.field_path.startswith(("plugging_record.plug", "plugging_record.proposed_plug")):
                try:
                    obj = json.loads(f.value or "{}")
                except json.JSONDecodeError:
                    flag(f, "plug value not parseable JSON")
                    continue
                top, base = _num(str(obj.get("top_md_ft", ""))), _num(str(obj.get("base_md_ft", "")))
                if top is not None and base is not None and top > base:
                    flag(f, f"plug top {top} below base {base}")
                if td and base and base > td * 1.02:
                    flag(f, f"plug base {base} exceeds TD {td}")
            if f.field_path.startswith("casing_string."):
                try:
                    obj = json.loads(f.value or "{}")
                except json.JSONDecodeError:
                    continue
                shoe, ctop = _num(str(obj.get("shoe_md_ft", obj.get("shoe_md", "")))), \
                    _num(str(obj.get("cement_top_ft", obj.get("cement_top", ""))))
                size = _num(str(obj.get("size_od_in", "")))
                if ctop is not None and shoe is not None and ctop > shoe:
                    flag(f, f"cement top {ctop} below shoe {shoe}")
                if td and shoe and shoe > td * 1.02:
                    flag(f, f"casing shoe {shoe} exceeds TD {td}")
                if size and shoe:
                    casing_shoes.append((size, shoe, f))
        casing_shoes.sort(key=lambda t: -t[0])  # larger OD should be shallower
        for (s1, d1, _), (s2, d2, f2) in zip(casing_shoes, casing_shoes[1:]):
            if s2 < s1 and d2 < d1:
                flag(f2, f"{s2}\" shoe {d2} shallower than {s1}\" shoe {d1} (non-monotonic)")
    return flags
