"""诊改待复核事项查询服务：由认领回执和异议回执共同生成，页面只读为主。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DiagnosisReviewService(BaseModuleService):
    MODULE = "diagnosis_review"
    ENTITY = "诊改待复核事项"
    LIST_FIELDS = [
        "review_no",
        "kind",
        "task_id",
        "task_number",
        "meeting_number",
        "resolution_code",
        "resolution_entry",
        "claim_receipt_no",
        "objection_receipt_no",
        "submission",
        "submitted_by",
    ]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["待复核", "复核通过，已验收"]
    ACTION_RULES = {"复核通过": "复核通过，已验收"}

    def run_action(self, entry_id: int, action: str, context=None):  # type: ignore[override]
        outcome = super().run_action(entry_id, action)
        if outcome[0] is not None and action == "复核通过":
            outcome[0]["status"] = "复核通过，已验收"
        return outcome
