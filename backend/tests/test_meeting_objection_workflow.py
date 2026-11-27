"""M-17 条目异议、认领冲突、回执幂等和诊改待复核联动测试。"""
from app.services.improve_task import ImproveTaskService
from app.services.review_meeting import ReviewMeetingService
from app.services.workflow import receipt_lookup
from app.store import store


def clear_all():
    for name in store.module_names():
        store.rows(name).clear()


def seed_pair():
    clear_all()
    meetings = ReviewMeetingService()
    tasks = ImproveTaskService()

    m17, _ = meetings.create_entry({
        "纪要编号": "M-17",
        "会议主题": "期中教学效果复盘",
        "参会人员": "主任、甲、乙",
        "召开日期": "2026-11-20",
        "决议事项": "1. 常规材料归档。\n2. 条目B：由乙提交试教记录任务。",
    })
    meetings.run_action(m17["id"], "签认纪要")
    meetings.run_action(m17["id"], "分发给教师")

    other, _ = meetings.create_entry({
        "纪要编号": "M-09",
        "会议主题": "另一份纪要",
        "参会人员": "主任、甲",
        "召开日期": "2026-11-19",
        "决议事项": "条目A：持续改进作业正确率任务。",
    })
    meetings.run_action(other["id"], "签认纪要")
    meetings.run_action(other["id"], "分发给教师")

    b = next(row for row in store.rows("improve_task") if row.get("resolution_code") == "B")
    a = next(row for row in store.rows("improve_task") if row.get("resolution_code") == "A")
    return meetings, tasks, m17, other, b, a


class TestMeetingObjectionWorkflow:
    def test_claim_first_replay_and_shared_review_item(self):
        meetings, tasks, m17, other, b, a = seed_pair()

        claim = tasks.run_action(b["id"], "认领任务", {
            "operator": "乙", "request_id": "claim-b-1",
        })
        assert claim.entry["status"] == "执行中"
        claim_no = claim.receipt["receipt_no"]

        objection = meetings.run_action(m17["id"], "提出异议", {
            "resolution_code": "B",
            "objector": "乙",
            "request_id": "objection-b-1",
        })
        assert m17["status"] == "已分发"
        assert objection.receipt["receipt_type"] == "异议回执"
        assert objection.receipt["meeting_number"] == "M-17"
        assert objection.receipt["resolution_code"] == "B"
        assert "由乙提交试教记录" in objection.receipt["resolution_entry"]
        assert objection.conflict["winner"] == "claim"

        # M-17 仍按已分发正本查阅；另一份纪要的 A 不受 B 异议影响。
        assert store.find("review_meeting", m17["id"])["status"] == "已分发"
        a_claim = tasks.run_action(a["id"], "认领任务", {"operator": "甲", "request_id": "claim-a-1"})
        assert a_claim.entry["status"] == "执行中"

        replay = tasks.run_action(b["id"], "认领任务", {
            "operator": "乙", "request_id": "claim-b-1",
        })
        assert replay.idempotent_replay is True
        assert replay.receipt["receipt_no"] == claim_no
        assert "B" in replay.message
        assert "原处理结果" in replay.message

        submitted = tasks.run_action(b["id"], "提交成果", {
            "request_id": "submit-b-1",
            "submission": "高等数学概念课试教记录",
            "objection_receipt_no": objection.receipt["receipt_no"],
        })
        assert submitted.entry["status"] == "待复核"
        assert submitted.review_item["status"] == "待复核"
        assert submitted.review_item["claim_receipt_no"] == claim_no
        assert submitted.review_item["objection_receipt_no"] == objection.receipt["receipt_no"]

        replay_submit = tasks.run_action(b["id"], "提交成果", {
            "request_id": "submit-b-1",
            "submission": "高等数学概念课试教记录",
            "objection_receipt_no": objection.receipt["receipt_no"],
        })
        assert replay_submit.idempotent_replay is True
        assert len(store.rows("diagnosis_review")) == 1

        assert receipt_lookup("claim-b-1")["original_task_number"] == "B"
        assert receipt_lookup("objection-b-1")["resolution_code"] == "B"
        assert receipt_lookup("submit-b-1")["review_no"] == submitted.review_item["review_no"]

    def test_objection_first_freezes_and_restore_allows_new_claim(self):
        meetings, tasks, m17, other, b, a = seed_pair()

        objection = meetings.run_action(m17["id"], "提出异议", {
            "resolution_index": 2,
            "objector": "主任",
            "request_id": "objection-first",
        })
        assert objection.entry["status"] == "已分发"
        assert b["status"] == "异议处理中"
        assert b["qualification_state"] == "异议优先，办理资格冻结"

        blocked = tasks.run_action(b["id"], "认领任务", {
            "operator": "乙", "request_id": "late-claim",
        })
        assert blocked.entry is None
        assert blocked.receipt["granted"] is False
        assert blocked.conflict["winner"] == "objection"

        blocked_replay = tasks.run_action(b["id"], "认领任务", {
            "operator": "乙", "request_id": "late-claim",
        })
        assert blocked_replay.idempotent_replay is True
        assert blocked_replay.receipt["receipt_no"] == blocked.receipt["receipt_no"]

        completed = meetings.run_action(m17["id"], "异议办理完成", {
            "objection_receipt_no": objection.receipt["receipt_no"],
            "handling_result": "核对无误，按原决议恢复",
            "request_id": "complete-1",
        })
        assert completed.receipt["status"] == "异议已办结"
        assert b["status"] == "待认领"
        assert b["qualification_state"] == "已按原决议恢复认领资格"

        renewed = tasks.run_action(b["id"], "认领任务", {
            "operator": "乙", "request_id": "new-claim-after-restore",
        })
        assert renewed.entry["status"] == "执行中"
        assert renewed.receipt["granted"] is True
        granted_claims = [
            row for row in store.rows("workflow_receipt")
            if row.get("kind") == "claim" and row.get("granted") and row.get("task_id") == b["id"]
        ]
        assert len(granted_claims) == 1

    def test_distributed_objection_does_not_become_draft_without_target_error(self):
        clear_all()
        meetings = ReviewMeetingService()
        m, _ = meetings.create_entry({
            "会议主题": "多决议",
            "参会人员": "全体",
            "召开日期": "2026-11-20",
            "决议事项": "第一条内容；第二条内容",
        })
        meetings.run_action(m["id"], "签认纪要")
        meetings.run_action(m["id"], "分发给教师")
        result, message = meetings.run_action(m["id"], "提出异议", {})
        assert result is None
        assert "指定异议对应" in message
        assert store.find("review_meeting", m["id"])["status"] == "已分发"
