from agent.rule_engine.rule_matcher import MatchedViolation
from agent.rule_engine.rule_loader import Rule


def compute_score(matched: list[MatchedViolation], rules: list[Rule], base: int | None = None) -> tuple[int, dict]:
    base = base if base is not None else 100
    total = sum(m.rule.weight for m in matched)
    score = max(0, base - total)
    breakdown = {
        "base": base,
        "total_deduction": total,
        "items": [
            {"rule_id": m.rule.rule_id, "rule_name": m.rule.rule_name,
             "category": m.rule.category, "risk_level": m.rule.risk_level,
             "weight": m.rule.weight}
            for m in matched
        ],
    }
    return score, breakdown
