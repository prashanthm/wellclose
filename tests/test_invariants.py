"""Regression tests for the enforced invariants and the determinism/plumbing fixes:
provenance gate (§8.3), deterministic conflict groups (§6.3 idempotency), pass-3 verify
score plumbing through the MCP submit path (§7D), and the README-documented eval CLI gate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_provenance_gate():
    """§8.3: no fact without page + verbatim snippet."""
    from wellclose.pipeline.extract import has_provenance
    assert has_provenance({"field_path": "wellbore.td_md_ft", "value": "3650",
                           "page": 3, "snippet": "T.D. 3650'"})
    assert not has_provenance({"field_path": "wellbore.td_md_ft", "value": "3650",
                               "snippet": "T.D. 3650'"})            # no page
    assert not has_provenance({"field_path": "wellbore.td_md_ft", "value": "3650",
                               "page": 3})                          # no snippet
    assert not has_provenance({"field_path": "wellbore.td_md_ft", "value": "3650",
                               "page": 0, "snippet": ""})           # falsy provenance


def test_conflict_group_id_deterministic():
    """§6.3: Temporal activity retries must regroup conflicts under the same id."""
    from wellclose.pipeline.resolve import conflict_group_id
    a = conflict_group_id("well-1", "wellbore.td_md_ft")
    assert a == conflict_group_id("well-1", "wellbore.td_md_ft")
    assert a != conflict_group_id("well-1", "well.operator")
    assert a != conflict_group_id("well-2", "wellbore.td_md_ft")
    assert len(a) == 32 and all(c in "0123456789abcdef" for c in a)


def test_inline_verify_scores_plumbed():
    """§7D pass-3: verify_confidence submitted inline per fact must survive the MCP layer."""
    from wellclose.mcp_server import inline_verify_scores
    facts = [
        {"field_path": "well.api_number", "value": "42-085-31234", "verify_confidence": 0.95},
        {"field_path": "well.operator", "value": "Example Oil Co."},          # no score
        {"field_path": "wellbore.td_md_ft", "value": "3650", "verify_confidence": 0},
        {"field_path": "well.spud_date", "value": "1955", "verify_confidence": "high"},  # junk
    ]
    assert inline_verify_scores(facts) == {0: 0.95, 2: 0.0}


def test_eval_cli_command_registered():
    """README documents `wellclose eval`; guard against the command disappearing."""
    from wellclose.cli import app
    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    assert "eval" in names


def test_classify_segment_coercion():
    """The small classifier's JSON shape varies; classify must never KeyError on it."""
    from wellclose.pipeline.classify import _coerce_segments, _norm_segment
    seg = [{"doc_type": "permit"}]
    assert _coerce_segments({"segments": seg}) == seg          # canonical
    assert _coerce_segments(seg) == seg                        # bare list
    assert _coerce_segments({"doc_type": "permit", "first_page": 1}) == \
        [{"doc_type": "permit", "first_page": 1}]              # lone unwrapped segment
    assert _coerce_segments({"result": seg}) == seg            # other wrapper key
    assert _coerce_segments("garbage") == [] and _coerce_segments({}) == []
    # normalization clamps page ranges and defaults bad fields
    assert _norm_segment({"doc_type": "plugging_record", "first_page": 2, "last_page": 99,
                          "confidence": 0.8}, total=16) == \
        {"doc_type": "plugging_record", "first_page": 2, "last_page": 16, "confidence": 0.8}
    assert _norm_segment({"doc_type": "bogus", "first_page": "x"}, total=10) == \
        {"doc_type": "unknown", "first_page": 1, "last_page": 10, "confidence": 0.5}


def test_validators_flag_physical_inconsistencies():
    """§7E validators are code, not LLM: plug top below base must flag."""
    from wellclose.pipeline.resolve import _num
    assert _num("3,650.5 ft") == 3650.5
    assert _num("TD 3650") == 3650.0
    assert _num("no depth") is None
