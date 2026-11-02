"""LLM 提案有效性与决策来源台账。

回答一个具体问题：本轮遍历里最终动作有多少真的来自模型、多少退化为
关键词兜底，以及模型提案被拒绝的原因分布。汇总值随 EngineResult.stats
与 ``llm_effectiveness_summary`` 事件落盘——fallback 占比一旦升高，
说明模型能力或提示词出现静默退化，必须可见而不是被兜底掩盖。
"""
from __future__ import annotations


class LLMEffectivenessLedger:
    def __init__(self) -> None:
        self._accepted = 0
        self._rejected = 0
        self._rejection_reasons: dict[str, int] = {}
        self._decisions_by_source: dict[str, int] = {}

    def record_proposal(self, *, status: str, fallback_reason: str = "") -> None:
        if status == "accepted":
            self._accepted += 1
            return
        self._rejected += 1
        key = str(fallback_reason or "unknown")
        self._rejection_reasons[key] = self._rejection_reasons.get(key, 0) + 1

    def record_final_decision(self, *, source: str) -> None:
        key = str(source or "unknown")
        self._decisions_by_source[key] = self._decisions_by_source.get(key, 0) + 1

    def summarize(self) -> dict:
        decisions_total = sum(self._decisions_by_source.values())
        fallback_decisions = int(self._decisions_by_source.get("fallback", 0))
        ratio: float | None = None
        if decisions_total:
            ratio = round(fallback_decisions / decisions_total, 4)
        return {
            "proposals_total": self._accepted + self._rejected,
            "proposals_accepted": self._accepted,
            "proposals_rejected": self._rejected,
            "rejection_reasons": dict(sorted(
                self._rejection_reasons.items(), key=lambda row: (-row[1], row[0]),
            )),
            "decisions_total": decisions_total,
            "fallback_decisions": fallback_decisions,
            "decision_sources": dict(sorted(
                self._decisions_by_source.items(), key=lambda row: (-row[1], row[0]),
            )),
            "fallback_ratio": ratio,
        }
