"""异议/认领回执查询服务；回执由工作流动作幂等写入，不通过通用动作修改。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class WorkflowReceiptService(BaseModuleService):
    MODULE = "workflow_receipt"
    ENTITY = "工作流回执"
    LIST_FIELDS = [
        "receipt_type",
        "receipt_no",
        "request_id",
        "kind",
        "status",
        "meeting_id",
        "meeting_number",
        "resolution_index",
        "resolution_code",
        "resolution_entry",
        "task_id",
        "task_number",
        "original_task_number",
        "claimant",
        "objector",
        "handling_instruction",
        "handling_result",
        "original_result",
    ]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["有效", "异议处理中", "异议已办结"]
    ACTION_RULES: dict[str, str] = {}
