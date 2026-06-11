"""Corpus selection + source-parser tests (T2.7). Service-free: synthetic fixtures only."""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _borehole(api, status="PA", year=1975, op="Apache Corporation", region="G"):
    return {"API_WELL_NUMBER": api, "WELL_NAME": f"W{api[:4]}", "COMPANY_NAME": op,
            "WELL_SPUD_DATE": f"1/1/{year}", "BOREHOLE_STAT_CD": status,
            "REGION_CODE": region, "BOTM_LEASE_NUMBER": "G0001",
            "BOTM_AREA_CODE": "EI", "BOTM_BLOCK_NUMBER": "100"}


def test_select_gom_wells_constraints():
    from wellclose.corpus import select_gom_wells
    ops = ["Fieldwood Energy LLC", "W & T Offshore, Inc.", "Chevron U.S.A. Inc.",
           "Other Oil Co.", "Another LLC"]
    rows = []
    for i in range(120):
        rows.append(_borehole(f"42700{i:05d}00", status="PA" if i % 3 else "TA",
                              year=1960 + (i % 60), op=ops[i % len(ops)]))
    rows.append(_borehole("99999999", region="P"))          # non-Gulf: excluded
    rows.append(_borehole("88888888", status="COM"))        # active: excluded
    sel = select_gom_wells(rows, n=50, min_pa=10, min_decom_ops=3)
    assert len(sel) == 50
    assert all(w["status"] in ("PA", "TA") for w in sel)
    assert sum(1 for w in sel if w["status"] == "PA") >= 10
    assert {w["stratum"] for w in sel} == {"pre-1990", "post-1990"}
    assert not any(w["api12"] in ("99999999", "88888888") for w in sel)
    # diversity: with 5 operators and n=50 the cap must spread picks across ALL of them
    from collections import Counter
    assert len(Counter(w["operator"] for w in sel)) == 5


def test_select_tx_wells_round_robin():
    from wellclose.corpus import select_tx_wells
    rows = []
    for d in ("01", "08", "7C", "09", "10", "03"):
        for i in range(50):
            rows.append({"DISTRICT_NAME": d, "API": f"{d.zfill(2)}93{i:04d}",
                         "OPERATOR_NAME": "OP", "LEASE_NAME": "L", "LEASE_ID": f"{i:05d}",
                         "WELL_NO": "1", "COUNTY_NAME": "C",
                         "CALC_MONTHS_P5_INACT": str(300 - i)})
    sel = select_tx_wells(rows, n=30)
    assert len(sel) == 30
    assert len({w["district"] for w in sel}) >= 5            # spread across districts
    assert sel[0]["stratum"] == "inact>=20y"                 # longest-inactive first
    # small-n regression: must not return empty when cap rounds to zero (12+ districts)
    assert len(select_tx_wells(rows, n=5)) == 5


def test_neusearch_payload_shape():
    from wellclose.sources.txrrc import TXRRCSource
    p = TXRRCSource.neusearch_payload(district="9", lease_number="120493", page_size=25)
    assert p["profile"] == 17 and p["strict"] == "true" and p["pageSize"] == 25
    items = {i["key"]: i for i in p["Searchitems"]["item"]}
    assert items["district"]["value"] == "09"                # zero-padded
    assert items["district"]["type"] == "DROPDOWN"
    assert items["lease_number"]["value"] == "120493"
    p2 = TXRRCSource.neusearch_payload(api8="23736907")
    assert {i["key"] for i in p2["Searchitems"]["item"]} == {"api_ft"}
    import pytest
    with pytest.raises(ValueError):
        TXRRCSource.neusearch_payload()


def test_bsee_explode_bulk_zip():
    from wellclose.sources.bsee import BSEESource
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data/file1.txt", b"alpha")
        z.writestr("data/", b"")                              # dir entry: skipped
        z.writestr("file2.csv", b"beta")
    members = BSEESource.explode_bulk_zip(buf.getvalue())
    assert sorted(n for n, _ in members) == ["data/file1.txt", "file2.csv"]
    assert dict(members)["file2.csv"] == b"beta"


def test_orphan_zip_href_regex():
    import re
    html = '<a href="/media/lzomznnu/orphanwells-05-26.zip">Orphan Well List</a>'
    m = re.search(r'href="(/media/[^"]*orphanwells[^"]*\.zip)"', html, re.I)
    assert m and m.group(1) == "/media/lzomznnu/orphanwells-05-26.zip"


def test_neubus_files_handles_list_or_dict_viewdata(monkeypatch):
    """getViewRecordOauth returns {tab:[entries]} normally but a bare [entries] for some
    records — both must parse without 'list has no attribute get' (full-pull regression)."""
    from wellclose.sources import txrrc as mod

    class FakeTX:
        _nde_post = mod.TXRRCSource._nde_post
        neubus_files = mod.TXRRCSource.neubus_files

        def __init__(self, viewdata, files):
            self._view = {"message": "success", "data": {"data": viewdata}}
            self._files = {"message": "success", "data": {"data": {"files": files}}}

        def _nde_post(self, path, payload):  # noqa: ARG002
            return self._view if "ViewRecord" in path else self._files

    entry = {"doc_id": "img1", "has_files": 1}
    f = [{"nuid": "n1", "name": "a.pdf", "format": "pdf", "page_count": "3", "file_size": "10"}]
    for viewdata in ({"Main": [entry]}, [entry]):       # dict form and bare-list form
        tx = FakeTX(viewdata, f)
        out = mod.TXRRCSource.neubus_files(tx, "doc")
        assert len(out) == 1 and out[0]["nuid"] == "n1"


def test_manifest_entry_key_stable():
    from wellclose.corpus import _entry_key
    e = {"source": "txrrc", "selector": {"well_documents": "30131005", "district": "08"}}
    same = {"source": "txrrc", "selector": {"district": "08", "well_documents": "30131005"}}
    assert _entry_key(e) == _entry_key(same)                 # key order must not matter
    assert _entry_key(e) != _entry_key({"source": "bsee", "selector": e["selector"]})
