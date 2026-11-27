"""诊改任务领域服务：任务分解、认领、异议冲突裁决、成果提交与复核联动。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.cross_module import check_entity_status
from app.services.workflow import (
    ActionOutcome,
    create_receipt,
    current_valid_claim,
    find_receipt_by_no,
    find_receipt_by_request,
    make_review_item,
    store,
    task_number,
    text,
)


class ImproveTaskService(BaseModuleService):
    MODULE = "improve_task"
    ENTITY = "诊改任务"
    OPERATION_TERM = "认领任务"
    LIST_FIELDS = ["任务编号", "任务描述", "承接方案", "执行人员", "起止日期", "验收标准", "督办人员", "任务权重", "备注说明"]
    REQUIRED_FIELDS = ["任务描述", "承接方案", "执行人员"]
    STATUS_ORDER = ["草稿", "待认领", "异议处理中", "执行中", "待复核", "已验收"]
    ACTION_RULES = {
        "认领任务": "执行中",
        "启动执行": "执行中",
        "提交成果": "待复核",
        "提交试教记录": "待复核",
        "申请验收": "已验收",
    }
    NEGATIVE_ACTIONS = []

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """创建诊改任务：承接方案引用必须是已审核通过的改进方案。"""
        source_plan = str(values.get("承接方案", "") or "").strip()

        # 尝试解析方案ID引用
        if source_plan.startswith("plan:"):
            plan_id_str = source_plan.split(":", 1)[1]
            try:
                plan_id = int(plan_id_str)
                check_entity_status(
                    "improve_plan", plan_id, ["审核通过"],
                    "诊改任务的承接方案"
                )
            except ValueError:
                pass

        entry, missing = super().create_entry(values)
        if entry is not None:
            entry.setdefault("qualification_state", "可认领")
            entry.setdefault("claim_entry_visible", entry.get("status") in {"草稿", "待认领"})
            for extra_key in (
                "task_code", "task_number", "source_meeting_id", "meeting_number",
                "resolution_index", "resolution_code", "source_objection_id",
            ):
                if values.get(extra_key) not in (None, ""):
                    entry[extra_key] = values[extra_key]
            if not entry.get("task_code") and values.get("任务编号"):
                entry["task_code"] = str(values["任务编号"]).strip()
        return entry, missing

    def run_action(
        self,
        entry_id: int,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str] | ActionOutcome:
        """执行动作，含认领幂等、异议冲突和提交复核。"""
        context = context or {}
        with store.lock:
            entry = self.get_entry(entry_id)
            if entry is None:
                return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

            if action == "认领任务":
                return self._claim(entry, context)

            if action in {"提交成果", "提交试教记录"}:
                return self._submit_result(entry, context)

            # 申请验收：成果提交后应处于待复核；兼容旧链路直接从执行中申请验收。
            if action == "申请验收":
                if entry.get("status") not in ("执行中", "待复核"):
                    return None, (
                        f"{self.ENTITY} {entry_id} 当前状态为'{entry.get('status')}'，"
                        "必须先执行或提交成果后再申请验收"
                    )

            outcome = super().run_action(entry_id, action)
            if action == "申请验收" and outcome[0] is not None:
                for review in store.rows("diagnosis_review"):
                    if review.get("task_id") == entry_id and review.get("status") == "待复核":
                        review["status"] = "复核通过，已验收"
                entry["qualification_state"] = "已验收"
            return outcome

    def _claim(
        self, entry: dict[str, Any], context: dict[str, Any]
    ) -> ActionOutcome:
        request_id = text(context, "request_id", "idempotency_key", "请求编号")
        replay = find_receipt_by_request(request_id, "claim")
        replay_known = (
            replay is not None
            and int(replay.get("task_id") or -1) == int(entry["id"])
            and (
                entry.get("claim_request_id") == request_id
                or entry.get("last_claim_request_id") == request_id
                or entry.get("claim_receipt_no") == replay.get("receipt_no")
            )
        )
        if replay_known and replay is not None:
            granted = bool(replay.get("granted"))
            task_ref = replay.get("original_task_number") or task_number(entry)
            original = replay.get("original_message") or replay.get("original_result") or replay.get("message") or "原认领结果已保留"
            replay_message = (
                f"同一次认领请求重试：原任务编号 {task_ref}（ID {entry['id']}）；原处理结果：{original}"
            )
            return ActionOutcome(
                entry if granted else None,
                replay_message,
                receipt=replay,
                conflict=replay.get("conflict"),
                idempotent_replay=True,
            )

        claimant = text(
            context,
            "operator", "claimant", "认领人", "执行人员", "claim_by",
            "teacher", "教师姓名", "办理人", "claimant_name",
            default=str(entry.get("执行人员") or "").strip() or "乙",
        )

        existing = current_valid_claim(entry)
        if existing:
            old_claimant = str(existing.get("claimant") or entry.get("执行人员") or "")
            if not old_claimant or old_claimant == claimant or existing.get("legacy"):
                # 同一办理人的重试必须查到原任务编号和原处理结果。
                receipt_no = str(existing.get("receipt_no") or entry.get("claim_receipt_no") or "")
                receipt = find_receipt_by_no(receipt_no) if receipt_no else existing
                message = (
                    f"认领请求已处理：原任务编号 {task_number(entry)}（ID {entry['id']}），"
                    f"当前状态'{entry.get('status')}'，正在返回原认领结果，请勿重复领取"
                )
                if request_id and isinstance(receipt, dict):
                    receipt.setdefault("request_id", request_id)
                return ActionOutcome(
                    entry, message,
                    receipt=receipt if isinstance(receipt, dict) else None,
                    idempotent_replay=True,
                )

            conflict = {
                "resource": task_number(entry),
                "winner": "other_claim",
                "current_claimant": old_claimant,
                "claim_receipt_no": existing.get("receipt_no"),
            }
            receipt = create_receipt(
                "认领请求结果",
                kind="claim",
                receipt_no=f"RL-{task_number(entry)}-REJECT-{store.next_operation_seq():04d}",
                request_id=request_id,
                task_id=entry["id"],
                task_number=task_number(entry),
                claimant=claimant,
                granted=False,
                status="已有有效办理资格",
                conflict=conflict,
                original_result="该任务已有其他有效认领人，不能重复取得办理资格",
            )
            return ActionOutcome(
                None,
                f"{task_number(entry)} 已由{old_claimant}取得唯一办理资格，不能重复认领",
                receipt=receipt,
                conflict=conflict,
            )

        active_objection_no = str(
            entry.get("objection_receipt_no") or context.get("objection_receipt_no") or ""
        )
        active_objection = find_receipt_by_no(active_objection_no) if active_objection_no else None
        if (
            entry.get("status") == "异议处理中"
            or entry.get("qualification_state") == "异议冻结"
            or (active_objection and active_objection.get("status") == "异议处理中")
        ):
            conflict = {
                "resource": task_number(entry),
                "rule": "server_commit_order_first_wins",
                "winner": "objection",
                "objection_receipt_no": active_objection_no,
            }
            blocked_message = (
                f"{task_number(entry)} 正处于异议处理窗口，异议优先；请等待异议办结并恢复资格后重新领取。"
                "本次请求编号可用于查询原处理结果"
            )
            if request_id:
                entry["last_claim_request_id"] = request_id
            receipt = create_receipt(
                "认领请求结果",
                kind="claim",
                receipt_no=f"RL-{task_number(entry)}-BLOCK-{store.next_operation_seq():04d}",
                request_id=request_id,
                task_id=entry["id"],
                task_number=task_number(entry),
                claimant=claimant,
                granted=False,
                status="异议优先，办理资格冻结",
                conflict=conflict,
                objection_receipt_no=active_objection_no,
                original_result=blocked_message,
                original_message=blocked_message,
            )
            return ActionOutcome(
                None,
                blocked_message,
                receipt=receipt,
                conflict=conflict,
            )

        if entry.get("status") not in ("待认领", "草稿"):
            conflict = {
                "resource": task_number(entry),
                "current_status": entry.get("status"),
                "current_receipt_no": entry.get("claim_receipt_no"),
            }
            return ActionOutcome(
                None,
                f"{self.ENTITY} {entry['id']} 当前状态为'{entry.get('status')}'，不可认领",
                conflict=conflict,
            )

        result_entry, base_message = super().run_action(entry["id"], "认领任务")
        entry["执行人员"] = claimant
        entry["qualification_state"] = "已认领，唯一办理资格有效"
        entry["claim_request_id"] = request_id
        receipt_id = max(
            (int(row.get("id", 0)) for row in store.rows("workflow_receipt")), default=0
        ) + 1
        receipt_no = f"RL-{task_number(entry)}-{receipt_id:04d}"
        receipt = create_receipt(
            "认领回执",
            kind="claim",
            receipt_no=receipt_no,
            request_id=request_id,
            task_id=entry["id"],
            task_number=task_number(entry),
            original_task_id=entry["id"],
            original_task_number=task_number(entry),
            claimant=claimant,
            granted=True,
            status="有效",
            action_result=base_message,
            original_result=f"认领成功，任务 {task_number(entry)} 进入执行中",
        )
        entry["claim_receipt_no"] = receipt_no
        entry["claim_seq"] = receipt["operation_seq"]

        # 若异议回执已先到达但未把状态冻结（异常/旧数据），在这里建立关联而不是发第二份资格。
        objection_ref = text(context, "objection_receipt_no", "receipt_no")
        objection = find_receipt_by_no(objection_ref) if objection_ref else None
        if objection is None and entry.get("objection_receipt_no"):
            objection = find_receipt_by_no(str(entry["objection_receipt_no"]))
        if objection and objection.get("status") == "异议处理中":
            receipt["objection_receipt_no"] = objection.get("receipt_no")
            receipt["qualification_decision"] = "claim_first"
            objection["claim_receipt_no"] = receipt_no
            entry["qualification_state"] = "原认领优先，可凭异议回执提交复核成果"

        message = (
            f"认领成功：{receipt_no}；原任务编号 {task_number(entry)}（ID {entry['id']}），"
            "该窗口内只保留这一份有效办理资格"
        )
        receipt["message"] = message
        receipt["original_message"] = message
        receipt["original_result"] = message
        return ActionOutcome(entry, message, receipt=receipt)

    def _submit_result(
        self, entry: dict[str, Any], context: dict[str, Any]
    ) -> ActionOutcome:
        request_id = text(context, "request_id", "idempotency_key", "提交请求编号")
        existing_review = None
        if request_id:
            for review in store.rows("diagnosis_review"):
                if review.get("request_id") == request_id and int(review.get("task_id") or -1) == int(entry["id"]):
                    existing_review = review
                    break
        if existing_review is None:
            for review in reversed(store.rows("diagnosis_review")):
                if review.get("task_id") == entry["id"] and review.get("status") == "待复核":
                    existing_review = review
                    break
        if existing_review is not None:
            return ActionOutcome(
                entry,
                f"原提交已生成诊改待复核事项 {existing_review.get('review_no')}，正在返回原处理结果",
                review_item=existing_review,
                idempotent_replay=True,
            )

        claim_request = text(context, "claim_request_id", "认领请求编号")
        claim_no = text(context, "claim_receipt_no", "认领回执编号")
        claim = find_receipt_by_request(claim_request, "claim") if claim_request else None
        if claim is None and claim_no:
            maybe_claim = find_receipt_by_no(claim_no)
            if maybe_claim and maybe_claim.get("kind") == "claim":
                claim = maybe_claim
        if claim is None:
            claim = current_valid_claim(entry)

        if not claim or not claim.get("granted"):
            receipt = create_receipt(
                "成果提交拦截回执",
                kind="submission_blocked",
                request_id=request_id,
                task_id=entry["id"],
                task_number=task_number(entry),
                granted=False,
                original_result="未查到同一次有效认领请求，不能凭原认领提交成果；请待异议解决后重新领取",
            )
            return ActionOutcome(
                None,
                "未查到该任务的有效认领资格，不能提交试教记录；请确认原认领回执，或等待争议解决后重新领取",
                receipt=receipt,
                conflict={"winner": "objection", "resource": task_number(entry)},
            )

        # 用认领回执校正当前任务，避免拿旧回执操作另一个任务。
        if int(claim.get("task_id") or entry["id"]) != int(entry["id"]):
            return None, "认领回执与当前原任务编号不一致，不能提交成果"

        objection_ref = text(
            context,
            "objection_receipt_no", "异议回执编号", "receipt_no", "objection_receipt",
        )
        objection = find_receipt_by_no(objection_ref) if objection_ref else None
        if objection is None and entry.get("objection_receipt_no"):
            objection = find_receipt_by_no(str(entry["objection_receipt_no"]))

        if entry.get("active_objection") or (
            objection and objection.get("status") == "异议处理中"
        ):
            if objection is None:
                return None, "请提供针对该决议条目的异议回执编号，再按回执打开原任务提交成果"
            if int(objection.get("task_id") or objection.get("original_task_id") or entry["id"]) != int(entry["id"]):
                return None, "异议回执中的原任务编号与当前任务不一致"
            if not claim.get("receipt_no"):
                return None, "缺少同一次认领请求对应的认领回执，无法生成待复核事项"

        submission = text(
            context,
            "submission", "result_content", "试教记录", "成果内容", "成果", "content",
            "试教记录内容", "trial_teaching_record", "record", "成果材料",
            default="已按要求提交试教记录",
        )
        submitted_by = text(
            context, "submitted_by", "operator", "提交人", "执行人",
            "教师姓名", "办理人",
            default=str(claim.get("claimant") or entry.get("执行人员") or "乙"),
        )

        super().run_action(entry["id"], "提交成果")
        entry["last_submission"] = submission
        entry["submitted_by"] = submitted_by

        review = make_review_item(
            task=entry,
            claim_receipt=claim,
            objection_receipt=objection,
            submission=submission,
            submitted_by=submitted_by,
            request_id=request_id,
        )
        receipts = [r for r in (claim, objection) if isinstance(r, dict)]
        message = (
            f"已按异议回执 {objection.get('receipt_no') if objection else ''} 打开原任务 "
            f"{task_number(entry)} 并提交试教记录；已生成诊改待复核事项 {review['review_no']}"
        )
        return ActionOutcome(
            entry, message, review_item=review, receipts=receipts,
            receipt=objection if objection else claim,
        )
