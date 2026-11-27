"""复盘会议领域服务：纪要签认、分发、条目异议、异议回执与资格恢复。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.workflow import (
    ActionOutcome,
    context_value,
    create_receipt,
    find_receipt_by_no,
    find_receipt_by_request,
    find_tasks_for_resolution,
    make_review_item,  # noqa: F401  # 保持工作流能力在领域服务层可见
    meeting_number,
    parse_resolution_entries,
    receipts_for,
    select_resolution_entry,
    store,
    task_number,
    text,
    current_valid_claim,
)

OBJECTION_COMPLETE_ACTIONS = {
    "办理异议",
    "异议办理完成",
    "完成异议办理",
    "异议办结",
    "处理异议",
}
RESTORE_ACTIONS = {"恢复分发资格", "恢复办理资格"}


class ReviewMeetingService(BaseModuleService):
    MODULE = "review_meeting"
    ENTITY = "会议纪要"
    OPERATION_TERM = "签认纪要"
    LIST_FIELDS = ["纪要编号", "会议主题", "参会人员", "召开日期", "决议事项", "分歧观点", "记录人员", "下次会议", "备注说明"]
    REQUIRED_FIELDS = ["会议主题", "参会人员", "召开日期"]
    STATUS_ORDER = ["草稿", "待签认", "已签认", "已分发"]
    ACTION_RULES = {
        "签认纪要": "已签认",
        "提出异议": "已分发",
        "分发给教师": "已分发",
        **{action: "已分发" for action in OBJECTION_COMPLETE_ACTIONS | RESTORE_ACTIONS},
    }
    NEGATIVE_ACTIONS = []

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        entry, missing = super().create_entry(values)
        if entry is not None:
            for extra_key in ("meeting_number", "resolution_entries", "source_quality_report_id"):
                if values.get(extra_key) not in (None, ""):
                    entry[extra_key] = values[extra_key]
        return entry, missing

    def run_action(
        self,
        entry_id: int,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str] | ActionOutcome:
        """执行会议动作。异议只冻结相关决议/任务资格，不把整份已分发纪要退回草稿。"""
        with store.lock:
            entry = self.get_entry(entry_id)
            if entry is None:
                return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

            if action == "签认纪要":
                if entry.get("status") not in ("待签认", "草稿"):
                    return None, f"{self.ENTITY} {entry_id} 当前状态为'{entry.get('status')}'，不可签认"
                return super().run_action(entry_id, action)

            if action == "分发给教师":
                if entry.get("status") != "已签认":
                    return None, f"{self.ENTITY} {entry_id} 必须先签认纪要，才能分发"
                result_entry, message = super().run_action(entry_id, action)
                if result_entry:
                    self._create_tasks_for_resolutions(result_entry)
                return result_entry, message

            if action == "提出异议":
                return self._raise_objection(entry, context or {})

            if action in OBJECTION_COMPLETE_ACTIONS:
                return self._complete_objection(entry, context or {})

            if action in RESTORE_ACTIONS:
                return self._restore_from_context(entry, context or {})

            return super().run_action(entry_id, action)

    def _raise_objection(
        self, meeting: dict[str, Any], context: dict[str, Any]
    ) -> ActionOutcome | tuple[None, str]:
        request_id = text(context, "request_id", "idempotency_key", "请求编号")
        replay = find_receipt_by_request(request_id, "objection")
        known_requests = meeting.get("objection_request_ids")
        known_numbers = meeting.get("objection_receipt_nos")
        replay_known = (
            replay is not None
            and int(replay.get("meeting_id") or -1) == int(meeting["id"])
            and (
                (isinstance(known_requests, list) and request_id in known_requests)
                or (isinstance(known_numbers, list) and replay.get("receipt_no") in known_numbers)
            )
        )
        if replay_known and replay is not None:
            return ActionOutcome(
                meeting,
                str(replay.get("original_message") or "该异议已受理，正在返回原异议回执"),
                receipt=replay,
                idempotent_replay=True,
            )

        if meeting.get("status") != "已分发":
            return None, (
                f"{self.ENTITY} {meeting['id']} 当前状态为'{meeting.get('status')}'；"
                "只有已分发纪要可针对具体决议条目提出异议，原纪要不会被退回草稿"
            )

        item, error = select_resolution_entry(meeting, context)
        if item is None and "多条决议" in error:
            # 页面/旧调用未选条目时，若整份纪要只有一条已派生诊改任务，可安全定位到该条目。
            linked_entries = [
                candidate
                for candidate in parse_resolution_entries(meeting)
                if find_tasks_for_resolution(meeting, candidate)
            ]
            if len(linked_entries) == 1:
                item = linked_entries[0]
                error = ""
        if item is None:
            return None, error

        objector = text(
            context,
            "objector", "异议人", "提出人", "教师", "operator",
            "异议教师", "提出异议人", "教师姓名", "objector_name",
            default="参会教师",
        )
        reason = text(
            context,
            "objection_reason", "异议内容", "reason", "comment", "remark",
            "异议理由", "意见", "objection",
            default="对该决议条目有异议，请复核",
        )

        # 无 request_id 时的自然幂等：同一人对同一条目的在办异议只开一张回执。
        if not request_id:
            for old in reversed(store.rows("workflow_receipt")):
                if (
                    old.get("kind") == "objection"
                    and old.get("meeting_id") == meeting["id"]
                    and old.get("objector") == objector
                    and int(old.get("resolution_index") or -1) == int(item["index"])
                    and old.get("status") == "异议处理中"
                ):
                    return ActionOutcome(
                        meeting,
                        "该异议已受理，正在返回原异议回执",
                        receipt=old,
                        idempotent_replay=True,
                    )

        tasks = find_tasks_for_resolution(meeting, item)
        task = tasks[0] if tasks else None
        task_id = int(task["id"]) if task else None
        task_no = task_number(task) if task else ""
        claim = current_valid_claim(task) if task else None

        m_no = meeting_number(meeting)
        resolution_key = item.get("code") or str(item["index"])
        receipt_id = max(
            (int(row.get("id", 0)) for row in store.rows("workflow_receipt")), default=0
        ) + 1
        receipt_no = f"YY-{m_no}-{resolution_key}-{receipt_id:04d}"

        if task is not None:
            if claim is not None:
                # 已先取得的认领资格不被后来的异议覆盖；两份回执共同决定送复核。
                task["qualification_state"] = "原认领优先，可凭异议回执提交复核成果"
                task["objection_receipt_no"] = receipt_no
                task["active_objection"] = True
                qualification_decision = "claim_first"
                handling_instruction = (
                    f"认领请求已先取得{task_no}的唯一办理资格；乙可凭认领回执和本异议回执"
                    "打开原任务提交试教记录，成果将随原认领送交复核，无需重新领取"
                )
                conflict = {
                    "resource": task_no,
                    "rule": "server_commit_order_first_wins",
                    "winner": "claim",
                    "claim_receipt_no": claim.get("receipt_no"),
                    "objection_receipt_no": receipt_no,
                }
            else:
                task.setdefault("pre_objection_status", task.get("status", "待认领"))
                task["status"] = "异议处理中"
                task["pending"] = True
                task["abnormal"] = True
                task["qualification_state"] = "异议优先，办理资格冻结"
                task["claim_entry_visible"] = False
                task["objection_receipt_no"] = receipt_no
                task["active_objection"] = True
                qualification_decision = "objection_first"
                handling_instruction = (
                    f"异议已先冻结{task_no}的办理资格；请等待异议办理完成并恢复资格后重新领取，"
                    "当前不能凭未确认的认领提交成果"
                )
                conflict = {
                    "resource": task_no,
                    "rule": "server_commit_order_first_wins",
                    "winner": "objection",
                    "objection_receipt_no": receipt_no,
                }
        else:
            qualification_decision = "no_linked_task"
            handling_instruction = "未找到该决议条目对应的诊改任务；异议办结后按原决议恢复分发资格"
            conflict = None

        receipt = create_receipt(
            "异议回执",
            kind="objection",
            receipt_no=receipt_no,
            request_id=request_id,
            meeting_id=meeting["id"],
            meeting_number=m_no,
            resolution_index=item["index"],
            resolution_code=item.get("code", ""),
            resolution_entry=item["text"],
            objector=objector,
            objection_reason=reason,
            status="异议处理中",
            original_task_id=task_id,
            task_id=task_id,
            original_task_number=task_no,
            task_number=task_no,
            claim_receipt_no=(claim or {}).get("receipt_no", ""),
            qualification_decision=qualification_decision,
            handling_instruction=handling_instruction,
            handling_result="",
            original_message="",
        )
        receipt["original_message"] = (
            f"异议已受理：{receipt_no}，已注明{m_no}第{item['index']}条决议条目"
            + (f"（{item.get('code')}）" if item.get("code") else "")
        )

        meeting["status"] = "已分发"  # 关键修复：已分发正本不退回草稿。
        meeting["objection_status"] = "异议处理中"
        meeting["distribution_qualification"] = "相关决议条目资格冻结，正本仍可查阅"
        meeting["has_active_objection"] = True
        meeting["abnormal"] = True
        meeting.setdefault("objection_receipt_nos", []).append(receipt_no)
        if request_id:
            meeting.setdefault("objection_request_ids", []).append(request_id)
        states = meeting.setdefault("resolution_states", {})
        states[resolution_key] = {
            "status": "异议处理中",
            "objection_receipt_no": receipt_no,
            "resolution_index": item["index"],
            "resolution_code": item.get("code", ""),
        }

        message = f"{receipt['original_message']}。{handling_instruction}"
        receipt["original_message"] = message
        receipt["original_result"] = message
        return ActionOutcome(meeting, message, receipt=receipt, conflict=conflict)

    def _resolve_objection_receipt(
        self, meeting: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        ref = text(
            context,
            "objection_receipt_no", "receipt_no", "回执编号", "异议回执编号", "receipt",
        )
        receipt = find_receipt_by_no(ref)
        if receipt and receipt.get("kind") == "objection":
            return receipt

        request_id = text(context, "request_id", "idempotency_key")
        receipt = find_receipt_by_request(request_id, "objection")
        if receipt:
            return receipt

        item, _ = select_resolution_entry(meeting, context)
        wanted_index = item["index"] if item else None
        for old in reversed(store.rows("workflow_receipt")):
            if (
                old.get("kind") == "objection"
                and old.get("meeting_id") == meeting["id"]
                and old.get("status") == "异议处理中"
                and (wanted_index is None or int(old.get("resolution_index") or -1) == wanted_index)
            ):
                return old

        active = [
            old for old in receipts_for(meeting_id=meeting["id"])
            if old.get("kind") == "objection" and old.get("status") == "异议处理中"
        ]
        return active[-1] if active else None

    def _complete_objection(
        self, meeting: dict[str, Any], context: dict[str, Any]
    ) -> ActionOutcome | tuple[None, str]:
        request_id = text(context, "request_id", "idempotency_key")
        replay = find_receipt_by_request(request_id)
        if replay and replay.get("kind") == "objection" and replay.get("status") != "异议处理中":
            return ActionOutcome(
                meeting,
                str(replay.get("completion_message") or "该异议已办结，正在返回原处理结果"),
                receipt=replay,
                idempotent_replay=True,
            )

        receipt = self._resolve_objection_receipt(meeting, context)
        if receipt is None:
            return None, "未找到需要办理的异议回执；请在异议回执中核对回执编号"

        if receipt.get("status") != "异议处理中":
            return ActionOutcome(
                meeting,
                f"异议回执 {receipt.get('receipt_no')} 已办结，处理结果保持不变",
                receipt=receipt,
                idempotent_replay=True,
            )

        result = text(
            context,
            "handling_result", "处理结果", "办理结果", "result", "decision", "remark",
            default="异议已处理，按原决议恢复相关资格",
        )
        receipt["status"] = "异议已办结"
        receipt["handling_result"] = result
        receipt["completed_request_id"] = request_id
        receipt["distribution_restored"] = True
        meeting["distribution_qualification"] = "已恢复"
        meeting["distribution_status"] = "异议办结，已按原决议恢复分发资格"

        item = {
            "index": receipt.get("resolution_index") or 1,
            "code": receipt.get("resolution_code", ""),
            "text": receipt.get("resolution_entry", ""),
        }
        key = item.get("code") or str(item["index"])
        states = meeting.setdefault("resolution_states", {})
        states[key] = {
            "status": "已恢复分发",
            "objection_receipt_no": receipt.get("receipt_no"),
            "handling_result": result,
        }

        task = None
        task_id = receipt.get("task_id") or receipt.get("original_task_id")
        if task_id:
            task = store.find("improve_task", int(task_id))
        if task is None:
            tasks = find_tasks_for_resolution(meeting, item)
            task = tasks[0] if tasks else None

        claim = current_valid_claim(task) if task else None
        restored = ""
        if task is not None:
            if claim is not None:
                task["qualification_state"] = "异议办结，原认领继续有效，可提交复核"
                task["active_objection"] = False
                task["claim_entry_visible"] = True
                receipt["claim_receipt_no"] = claim.get("receipt_no") or receipt.get("claim_receipt_no", "")
                restored = "原认领资格继续有效，乙可直接提交试教记录"
            else:
                previous = task.get("pre_objection_status")
                restore_status = previous if previous in {"草稿", "待认领"} else "待认领"
                task["status"] = restore_status
                task["pending"] = restore_status != "已验收"
                task["abnormal"] = False
                task["qualification_state"] = "已按原决议恢复认领资格"
                task["claim_entry_visible"] = True
                task["active_objection"] = False
                restored = f"{task_number(task)}已恢复为{restore_status}，可重新认领"
            receipt["restored_qualification"] = restored

        active = [
            row for row in store.rows("workflow_receipt")
            if row.get("kind") == "objection"
            and row.get("meeting_id") == meeting["id"]
            and row.get("status") == "异议处理中"
        ]
        if not active:
            meeting["objection_status"] = "异议已办结，分发资格已恢复"
            meeting["has_active_objection"] = False
            meeting["abnormal"] = False
        else:
            meeting["objection_status"] = "部分异议处理中"

        message = (
            f"异议回执 {receipt['receipt_no']} 已办理完成：{result}；"
            f"{restored if task else '已按原决议恢复分发资格'}"
        )
        receipt["completion_message"] = message
        return ActionOutcome(meeting, message, receipt=receipt)

    def _restore_from_context(
        self, meeting: dict[str, Any], context: dict[str, Any]
    ) -> ActionOutcome | tuple[None, str]:
        receipt = self._resolve_objection_receipt(meeting, context)
        if receipt is None:
            return None, "未找到可恢复资格的异议回执"
        if receipt.get("status") == "异议处理中":
            context = {**context, "handling_result": text(context, default="经复核，按原决议恢复分发资格")}
            return self._complete_objection(meeting, context)
        return ActionOutcome(
            meeting,
            f"异议 {receipt.get('receipt_no')} 已办结，原决议分发资格处于恢复状态",
            receipt=receipt,
            idempotent_replay=True,
        )

    def _create_tasks_for_resolutions(self, meeting: dict[str, Any]) -> None:
        """分发后按决议条目创建任务；保留旧调用名以兼容已有测试/脚本。"""
        self._maybe_create_improve_task(
            meeting.get("会议主题", ""), meeting.get("决议事项", ""), int(meeting["id"]), meeting
        )

    def _maybe_create_improve_task(
        self,
        theme: str,
        resolution: str,
        meeting_id: int,
        meeting: dict[str, Any] | None = None,
    ) -> None:
        """根据会议决议创建诊改任务：按 meeting 标记幂等，不重复创建。"""
        task_rows = store.rows("improve_task")
        for row in task_rows:
            if f"meeting:{meeting_id}" in str(row.get("任务描述", "")):
                return

        meeting_ref = meeting or store.find("review_meeting", meeting_id) or {}
        entries = parse_resolution_entries(meeting_ref) if meeting_ref else []
        actionable = [
            item for item in entries
            if "任务" in item["text"] or item.get("code")
        ]
        if not actionable and resolution and "任务" in str(resolution):
            actionable = [{"index": 1, "code": "", "text": resolution}]

        # 旧逻辑在整段决议含“任务”时只生成一个任务；多条目明确带编号时才拆分。
        if len(actionable) > 1 and all(item.get("code") for item in actionable):
            targets = actionable
        else:
            targets = actionable[:1] if actionable else []

        m_no = meeting_number({"id": meeting_id, **meeting_ref}) if meeting_ref else f"M-{meeting_id}"
        for item in targets:
            new_id = max((int(r.get("id", 0)) for r in task_rows), default=0) + 1
            code = item.get("code", "")
            code_part = f"任务 {code} " if code else ""
            task_rows.append({
                "id": new_id,
                "task_code": code,
                "task_number": code or f"T-{new_id}",
                "source_meeting_id": meeting_id,
                "meeting_number": m_no,
                "resolution_index": item.get("index", 1),
                "resolution_code": code,
                "任务描述": f"会议决议：{theme} {code_part}[meeting:{meeting_id}]",
                "承接方案": item.get("text", resolution),
                "执行人员": "",
                "起止日期": "",
                "验收标准": "",
                "督办人员": "",
                "任务权重": "",
                "备注说明": "由复盘会议决议自动生成",
                "status": "待认领",
                "pending": True,
                "abnormal": False,
                "qualification_state": "可认领",
                "claim_entry_visible": True,
            })
