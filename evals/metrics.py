"""Eval metrics (Brief §10.2): field-level precision/recall, confidence calibration,
classification accuracy, per-era breakdown."""
from __future__ import annotations
import re


_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _norm(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "").strip().lower())


def value_match(pred: str, gold: str, numeric_tol: float = 0.01) -> bool:
    p, g = _norm(pred), _norm(gold)
    if p == g:
        return True
    pm, gm = _NUM.search(p), _NUM.fullmatch(g) or _NUM.search(g)
    if pm and gm and (_NUM.fullmatch(g) or _NUM.fullmatch(p)):
        pf = float(pm.group(0).replace(",", ""))
        gf = float(gm.group(0).replace(",", ""))
        return abs(pf - gf) <= max(abs(gf) * numeric_tol, 0.51)
    return False


def field_prf(pred_facts: list[dict], gold_facts: list[dict]) -> dict:
    """Match on (field_path, value); gold 'multi' fields match any-of. Returns P/R/F1 + pairs."""
    gold_left = list(gold_facts)
    tp, matched_pred = 0, set()
    for i, p in enumerate(pred_facts):
        for g in gold_left:
            if g["field_path"] == p["field_path"] and value_match(str(p["value"]), str(g["value"])):
                tp += 1
                matched_pred.add(i)
                gold_left.remove(g)
                break
    fp = len(pred_facts) - tp
    fn = len(gold_left)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4),
            "missed": [g["field_path"] for g in gold_left],
            "spurious": [p["field_path"] for i, p in enumerate(pred_facts)
                         if i not in matched_pred]}


def calibration(pred_facts: list[dict], gold_facts: list[dict], threshold: float = 0.9) -> dict:
    """Of facts predicted with confidence >= threshold, what fraction are correct? (§10.2 target >=95%)."""
    high = [p for p in pred_facts if float(p.get("confidence", 0)) >= threshold]
    if not high:
        return {"threshold": threshold, "n": 0, "accuracy": None}
    correct = 0
    pool = list(gold_facts)
    for p in high:
        for g in pool:
            if g["field_path"] == p["field_path"] and value_match(str(p["value"]), str(g["value"])):
                correct += 1
                pool.remove(g)
                break
    return {"threshold": threshold, "n": len(high), "accuracy": round(correct / len(high), 4)}


def classification_accuracy(pred: dict[str, str], gold: dict[str, str]) -> dict:
    keys = set(gold)
    if not keys:
        return {"n": 0, "accuracy": None}
    correct = sum(1 for k in keys if pred.get(k) == gold[k])
    return {"n": len(keys), "accuracy": round(correct / len(keys), 4),
            "errors": {k: {"pred": pred.get(k), "gold": gold[k]}
                       for k in keys if pred.get(k) != gold[k]}}
