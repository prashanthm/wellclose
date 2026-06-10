"""Service-free unit tests: validators math, API normalization, rubric gap logic, templates,
agent specs, eval metrics. Integration tests (Docker/Ollama) are your local first-run (TASKS.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_normalize_api():
    from wellclose.pipeline.resolve import normalize_api
    assert normalize_api("API No. 42-085-31234") == "420853123400"
    assert normalize_api("42 085 31234 01") == "420853123401"
    assert normalize_api("no api here") is None


def test_template_loading():
    from wellclose.pipeline.extract import load_template
    tpl = load_template("plugging_record")
    assert tpl["doc_type"] == "plugging_record"
    paths = [f["field_path"] for f in tpl["fields"]]
    assert "plugging_record.plug" in paths and "well.api_number" in paths
    assert load_template("wellbore_schematic")["diagram"] is True
    assert load_template("no_such_type") is None


def test_rubric_files_valid():
    from wellclose.rubric import load_rubric
    for jur in ("TXRRC", "BSEE"):
        r = load_rubric(jur)
        assert len(r["requirements"]) >= 8
        for req in r["requirements"]:
            assert req["criticality"] in ("blocker", "major", "minor")
            assert req["satisfied_by"] and req["id"]


def test_agent_specs_valid():
    import yaml
    spec_dir = Path(__file__).parent.parent / "src/wellclose/agents/specs"
    names = {p.stem for p in spec_dir.glob("*.yaml")}
    assert names == {"acquisition_agent", "intake_agent", "extraction_agent",
                     "historian_agent", "gap_rubric_agent", "composer_agent"}
    mcp_tools = {"source_discover", "source_fetch", "corpus_status", "get_document_pages",
                 "get_ocr_text", "get_extraction_template", "submit_facts", "query_facts",
                 "search_documents", "get_rubric", "submit_gap_report", "get_well_summary",
                 "render_dossier", "flag_for_review"}
    for p in spec_dir.glob("*.yaml"):
        spec = yaml.safe_load(p.read_text())
        assert spec["model"] in ("vision", "text", "small")
        assert set(spec["tools"]) <= mcp_tools, f"{p.name} references unknown tool"
        assert "HARD RULE" in spec["system_prompt"] or "Brief §8" in spec["system_prompt"]


def test_composer_spec_enforces_approved_only():
    import yaml
    spec = yaml.safe_load((Path(__file__).parent.parent /
                           "src/wellclose/agents/specs/composer_agent.yaml").read_text())
    assert "approved" in spec["system_prompt"]


def test_eval_metrics():
    from evals.metrics import calibration, field_prf, value_match
    assert value_match("3,650 ft", "3650")
    assert value_match("3650.0", "3650")
    assert not value_match("3500", "3650")
    gold = [{"field_path": "wellbore.td_md_ft", "value": "3650"},
            {"field_path": "well.operator", "value": "Example Oil Co."}]
    pred = [{"field_path": "wellbore.td_md_ft", "value": "3650", "confidence": 0.97},
            {"field_path": "well.operator", "value": "Wrong Co.", "confidence": 0.5},
            {"field_path": "well.spud_date", "value": "1955-01-01", "confidence": 0.99}]
    prf = field_prf(pred, gold)
    assert prf["tp"] == 1 and prf["fp"] == 2 and prf["fn"] == 1
    cal = calibration(pred, gold, threshold=0.9)
    assert cal["n"] == 2 and cal["accuracy"] == 0.5


def test_sources_yaml_and_registry():
    from wellclose.sources.base import source_config
    from wellclose.sources.volve import REGISTRY
    cfg = source_config()
    assert set(REGISTRY) == {"bsee", "txrrc", "volve"}
    assert cfg["bsee"]["base"].startswith("https://")
    assert "wellbore_query" in cfg["txrrc"]


def test_fact_status_machine_values():
    """§5.1: append-only states."""
    from wellclose import models
    col = models.ExtractedFact.__table__.c.status
    assert col.default.arg == "proposed"


def test_workflow_signal_methods_exist():
    from wellclose.workflows.w1 import DossierGenerationWorkflow
    w = DossierGenerationWorkflow()
    assert hasattr(w, "review_complete") and hasattr(w, "sign_off")
    w.review_complete()
    w.sign_off("reviewer-1")
    assert w._review_complete and w._signed_off_by == "reviewer-1"
