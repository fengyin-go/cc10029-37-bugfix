"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import threading
from typing import Any

from app.seed import SEED_ROWS

INTERNAL_TABLES = {"workflow_receipt", "diagnosis_review"}


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 回执和待复核事项也是需要随测试/业务一起清理的内存表。
        self._tables.setdefault("workflow_receipt", [])
        self._tables.setdefault("diagnosis_review", [])
        self._seed_meeting_objection_scenario()
        self.lock = threading.RLock()
        self._operation_seq = 0

    def _seed_meeting_objection_scenario(self) -> None:
        """预置 M-17/B 与另一份纪要/A，便于直接复现冲突窗口。"""
        meetings = self._tables.setdefault("review_meeting", [])
        if not any(str(row.get("纪要编号")) == "M-17" for row in meetings):
            meetings.append({
                "id": 17,
                "纪要编号": "M-17",
                "status": "已分发",
                "pending": False,
                "abnormal": False,
                "会议主题": "第十一周教学复盘：试教记录与课堂互动改进",
                "参会人员": "教研室主任、甲、乙及相关教师",
                "召开日期": "2026-11-20",
                "决议事项": (
                    "1. 确认期中教学材料归档安排。\n"
                    "2. 条目B：由乙提交高等数学概念课试教记录，并按异议回执核对后进入诊改复核。"
                ),
                "分歧观点": "部分教师希望先核对试教记录对应的决议条目。",
                "记录人员": "教研室秘书",
                "下次会议": "2026-12-04",
                "备注说明": "M-17 正本已分发；条目异议只影响对应任务 B。",
            })

        if not any(str(row.get("纪要编号")) == "M-18" for row in meetings):
            meetings.append({
                "id": 18,
                "纪要编号": "M-18",
                "status": "已分发",
                "pending": False,
                "abnormal": False,
                "会议主题": "另一份课程组改进纪要",
                "参会人员": "教研室主任、甲",
                "召开日期": "2026-11-19",
                "决议事项": "条目A：持续跟进作业正确率改进任务。",
                "分歧观点": "",
                "记录人员": "教研室秘书",
                "下次会议": "",
                "备注说明": "任务 A 与 M-17/B 的异议隔离。",
            })

        tasks = self._tables.setdefault("improve_task", [])
        if not any(str(row.get("任务编号")) == "B" and row.get("source_meeting_id") == 17 for row in tasks):
            tasks.append({
                "id": 17,
                "任务编号": "B",
                "task_code": "B",
                "task_number": "B",
                "source_meeting_id": 17,
                "meeting_number": "M-17",
                "resolution_index": 2,
                "resolution_code": "B",
                "status": "待认领",
                "pending": True,
                "abnormal": False,
                "任务描述": "任务 B：提交高等数学概念课试教记录 [meeting:17]",
                "承接方案": "条目B：由乙提交高等数学概念课试教记录，并按异议回执核对后进入诊改复核。",
                "执行人员": "乙",
                "起止日期": "2026-11-21至2026-11-28",
                "验收标准": "试教记录完整，能对应 M-17 条目B并送交诊改复核",
                "督办人员": "教研室主任",
                "任务权重": "高",
                "备注说明": "等待乙认领；异议和认领按服务器受理顺序裁决。",
                "qualification_state": "可认领",
                "claim_entry_visible": True,
            })

        if not any(str(row.get("任务编号")) == "A" and row.get("source_meeting_id") == 18 for row in tasks):
            tasks.append({
                "id": 18,
                "任务编号": "A",
                "task_code": "A",
                "task_number": "A",
                "source_meeting_id": 18,
                "meeting_number": "M-18",
                "resolution_index": 1,
                "resolution_code": "A",
                "status": "执行中",
                "pending": False,
                "abnormal": False,
                "任务描述": "任务 A：跟进作业正确率改进 [meeting:18]",
                "承接方案": "条目A：持续跟进作业正确率改进任务。",
                "执行人员": "甲",
                "起止日期": "2026-11-20至2026-12-10",
                "验收标准": "作业正确率提升并有连续记录",
                "督办人员": "教研室主任",
                "任务权重": "中",
                "备注说明": "来自另一份纪要，M-17 的异议不影响该任务继续办理。",
                "qualification_state": "已认领，唯一办理资格有效",
                "claim_entry_visible": False,
            })

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def public_module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in INTERNAL_TABLES)

    def next_operation_seq(self) -> int:
        with self.lock:
            self._operation_seq += 1
            return self._operation_seq

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.public_module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
