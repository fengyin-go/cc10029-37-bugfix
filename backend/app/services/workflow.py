"""纪要异议、任务认领与待复核之间的共享工作流原语。

这里集中维护：
- 操作序列号和全局锁，决定并发请求谁先取得资格；
- 异议/认领回执与请求幂等键；
- M-17 一类纪要编号、决议条目和原任务之间的关联；
- 两处页面共享的同一份诊改待复核事项。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from app.store import store

INTERNAL_RECEIPT_TABLE = "workflow_receipt"
REVIEW_TABLE = "diagnosis_review"

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


class ActionOutcome:
    """同时兼容 `entry, message = service.run_action(...)` 解包和富回执响应。"""

    def __init__(
        self,
        entry: dict[str, Any] | None,
        message: str,
        *,
        receipt: dict[str, Any] | None = None,
        receipts: list[dict[str, Any]] | None = None,
        review_item: dict[str, Any] | None = None,
        conflict: dict[str, Any] | None = None,
        idempotent_replay: bool = False,
        status_code: int = 200,
    ) -> None:
        self.entry = entry
        self.message = message
        self.receipt = receipt
        self.receipts = receipts
        self.review_item = review_item
        self.conflict = conflict
        self.idempotent_replay = idempotent_replay
        self.status_code = status_code

    def __iter__(self) -> Iterable[Any]:
        yield self.entry
        yield self.message


def context_value(context: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not context:
        return default
    for key in keys:
        value = context.get(key)
        if value is not None and str(value).strip() != "":
            return value
    values = context.get("values")
    if isinstance(values, dict):
        for key in keys:
            value = values.get(key)
            if value is not None and str(value).strip() != "":
                return value
    return default


def text(context: dict[str, Any] | None, *keys: str, default: str = "") -> str:
    value = context_value(context, *keys, default=default)
    return str(value).strip() if value is not None else default


def meeting_number(meeting: dict[str, Any]) -> str:
    value = meeting.get("meeting_number") or meeting.get("纪要编号")
    return str(value).strip() if value else f"M-{meeting.get('id')}"


def task_number(task: dict[str, Any]) -> str:
    value = task.get("task_number") or task.get("任务编号")
    if value:
        return str(value).strip()
    code = task.get("task_code")
    if code:
        return str(code).strip()
    return f"T-{task.get('id')}"


def _normalize_index(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    if raw.isdigit():
        return int(raw)
    if raw in _CN_NUM:
        return _CN_NUM[raw]
    match = re.search(r"(\d+)", raw)
    return int(match.group(1)) if match else None


def parse_resolution_entries(meeting: dict[str, Any]) -> list[dict[str, Any]]:
    """把决议事项拆成可被异议回执引用的条目。"""
    stored = meeting.get("resolution_entries")
    if isinstance(stored, list) and stored:
        entries: list[dict[str, Any]] = []
        for idx, item in enumerate(stored, 1):
            if isinstance(item, dict):
                content = str(item.get("content") or item.get("text") or item.get("内容") or "").strip()
                entries.append({
                    "index": int(item.get("index") or idx),
                    "code": str(item.get("code") or item.get("编号") or "").strip(),
                    "text": content,
                })
            else:
                entries.append({"index": idx, "code": "", "text": str(item).strip()})
        return [item for item in entries if item["text"]]

    raw = str(meeting.get("决议事项") or "").strip()
    if not raw:
        return []

    # 先按换行拆；若一行内用序号/分号列出，再按条目前瞻拆分。
    chunks: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        pieces = re.split(
            r"\r?\n"
            r"|\s*(?:；|;)\s*"
            r"|\s*(?=(?:\d+|[一二三四五六七八九十]+)\s*[\.、．\)）])",
            line,
        )
        chunks.extend(piece.strip() for piece in pieces if piece and piece.strip())

    entries = []
    for enumerated_index, chunk in enumerate(chunks, 1):
        index = enumerated_index
        index_match = re.match(r"^(?:第)?(\d+|[一二三四五六七八九十]+)\s*[\.、．\)）条]?\s*", chunk)
        if index_match:
            parsed = _normalize_index(index_match.group(1))
            if parsed:
                index = parsed
            chunk = chunk[index_match.end():].strip()

        code = ""
        leading_code = re.match(
            r"^\s*(?:条目|决议|任务)?\s*([A-Z0-9]+)\s*[\.、．:：]\s*", chunk
        )
        if leading_code:
            code = leading_code.group(1)
            chunk = chunk[leading_code.end():].strip()
        else:
            code_match = re.search(r"(?:条目|决议|任务)\s*([A-Z])(?![A-Za-z0-9_:])", chunk)
            if code_match:
                code = code_match.group(1)

        marker_match = re.search(r"\[resolution:([A-Za-z0-9_-]+)\]", chunk)
        if marker_match:
            code = marker_match.group(1)
            chunk = chunk.replace(marker_match.group(0), "").strip()

        entries.append({"index": index, "code": code, "text": chunk})

    return entries or [{"index": 1, "code": "", "text": raw}]


def select_resolution_entry(
    meeting: dict[str, Any], context: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, str]:
    entries = parse_resolution_entries(meeting)
    if not entries:
        return None, "该纪要没有可提出异议的决议条目"

    wanted_index = _normalize_index(context_value(
        context, "resolution_index", "index", "条目序号", "决议序号", "resolution_no"
    ))
    wanted_code = text(
        context,
        "resolution_code", "code", "条目编号", "决议条目编号", "resolution",
        "异议条目编号", "条目代码",
    )
    wanted_text = text(
        context,
        "resolution_entry", "entry", "resolution_text", "决议条目", "target",
        "异议条目", "条目", "决议内容",
    )
    remark = text(context, "remark", "异议内容", "objection_reason", "reason", "comment")

    # 常见自然语言：“对第2条/第二条”或“针对条目B”。
    if wanted_index is None:
        m = re.search(r"第\s*(\d+|[一二三四五六七八九十]+)\s*条", f"{wanted_text} {remark}")
        if m:
            wanted_index = _normalize_index(m.group(1))
    if not wanted_code:
        m = re.search(r"(?:条目|决议|任务)\s*([A-Z])(?![A-Za-z0-9_:])", f"{wanted_text} {remark}")
        if m:
            wanted_code = m.group(1)
        elif re.fullmatch(r"[A-Z]", wanted_text.upper()):
            wanted_code = wanted_text.upper()

    if wanted_index is not None:
        for item in entries:
            if item["index"] == wanted_index:
                return item, ""
        return None, f"未找到第{wanted_index}条决议条目"

    if wanted_code:
        for item in entries:
            if item.get("code", "").upper() == wanted_code.upper():
                return item, ""
        return None, f"未找到编号为{wanted_code}的决议条目"

    if wanted_text and wanted_text not in {"提出异议"}:
        for item in entries:
            if wanted_text in item["text"] or item["text"] in wanted_text:
                return item, ""

    if len(entries) == 1:
        return entries[0], ""

    return None, "该纪要包含多条决议，请指定异议对应的决议条目编号或序号"


def _blob(row: dict[str, Any]) -> str:
    return " ".join(
        str(value) for key, value in row.items()
        if not key.startswith("_") and isinstance(value, (str, int, float))
    )


def source_meeting_id(task: dict[str, Any]) -> int | None:
    for key in ("source_meeting_id", "meeting_id", "来源纪要ID"):
        value = task.get(key)
        if value not in (None, ""):
            parsed = _normalize_index(value)
            if parsed is not None:
                return parsed
    blob = _blob(task)
    match = re.search(r"meeting:(\d+)", blob)
    if match:
        return int(match.group(1))
    match = re.search(r"\bM-(\d+)\b", blob)
    if match:
        return int(match.group(1))
    return None


def task_matches_resolution(task: dict[str, Any], item: dict[str, Any]) -> bool:
    task_code = str(
        task.get("resolution_code")
        or task.get("task_code")
        or task.get("决议条目编号")
        or ""
    ).upper()
    wanted_code = str(item.get("code") or "").upper()
    if wanted_code:
        if task_code == wanted_code:
            return True
        if re.search(rf"(?:任务|条目|决议)\s*{re.escape(wanted_code)}(?![A-Za-z0-9])", _blob(task)):
            return True
        if f"resolution:{wanted_code.lower()}" in _blob(task).lower():
            return True
        return False

    wanted_index = item.get("index")
    task_index = _normalize_index(task.get("resolution_index") or task.get("决议条目序号"))
    if task_index is not None:
        return task_index == wanted_index

    wanted_text = item.get("text", "")
    if wanted_text and len(wanted_text) >= 8:
        # 自动生成任务时会把整段决议放进“承接方案”。
        return wanted_text[:20] in _blob(task)
    return False


def task_belongs_to_meeting(task: dict[str, Any], meeting: dict[str, Any]) -> bool:
    meeting_id = int(meeting["id"])
    m_no = meeting_number(meeting)
    if task.get("source_meeting_id") in (meeting_id, str(meeting_id)):
        return True
    if str(task.get("meeting_number") or task.get("纪要编号") or "").strip() == m_no:
        return True

    blob = _blob(task)
    if f"meeting:{meeting_id}" in blob:
        return True
    if m_no and re.search(rf"{re.escape(m_no)}(?![0-9A-Za-z_-])", blob):
        return True

    # 外部数据可能把 M-17 的 17 直接写入 source_meeting_id。
    number_match = re.search(r"(\d+)$", m_no)
    if number_match and source_meeting_id(task) == int(number_match.group(1)):
        return True
    return False


def find_tasks_for_resolution(
    meeting: dict[str, Any], item: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    linked: list[dict[str, Any]] = []
    same_meeting: list[dict[str, Any]] = []
    for task in store.rows("improve_task"):
        if not task_belongs_to_meeting(task, meeting):
            continue
        same_meeting.append(task)
        if item is None or task_matches_resolution(task, item):
            linked.append(task)

    if linked:
        return linked
    # 旧数据没有逐条决议标记：同一份纪要只生成一个任务时可安全回退。
    if item is not None and len(same_meeting) == 1:
        return same_meeting
    return []


def next_row_id(table: str) -> int:
    rows = store.rows(table)
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def create_receipt(
    receipt_type: str,
    *,
    request_id: str = "",
    receipt_no: str = "",
    **fields: Any,
) -> dict[str, Any]:
    rows = store.rows(INTERNAL_RECEIPT_TABLE)
    receipt = {
        "id": next_row_id(INTERNAL_RECEIPT_TABLE),
        "receipt_type": receipt_type,
        "receipt_no": receipt_no,
        "request_id": request_id,
        "operation_seq": store.next_operation_seq(),
        **fields,
    }
    rows.append(receipt)
    return receipt


def find_receipt_by_request(request_id: str | None, kind: str | None = None) -> dict[str, Any] | None:
    if not request_id:
        return None
    for receipt in reversed(store.rows(INTERNAL_RECEIPT_TABLE)):
        if (
            receipt.get("request_id") != request_id
            and receipt.get("completed_request_id") != request_id
        ):
            continue
        if kind and receipt.get("kind") != kind:
            continue
        return receipt
    return None


def find_receipt_by_no(receipt_no: str | None) -> dict[str, Any] | None:
    if not receipt_no:
        return None
    wanted = str(receipt_no).strip()
    for receipt in store.rows(INTERNAL_RECEIPT_TABLE):
        if str(receipt.get("receipt_no", "")).casefold() == wanted.casefold():
            return receipt
    return find_receipt_by_request(wanted)


def receipts_for(*, task_id: int | None = None, meeting_id: int | None = None) -> list[dict[str, Any]]:
    result = []
    for receipt in store.rows(INTERNAL_RECEIPT_TABLE):
        if task_id is not None and receipt.get("task_id") == task_id:
            result.append(receipt)
        elif meeting_id is not None and receipt.get("meeting_id") == meeting_id:
            result.append(receipt)
    return result


def current_valid_claim(task: dict[str, Any]) -> dict[str, Any] | None:
    """返回当前有效认领回执；异议不会使先取得的认领失效。"""
    if task.get("qualification_state") in {"异议冻结", "已冻结"}:
        return None
    receipt_no = task.get("claim_receipt_no") or task.get("current_claim_receipt_no")
    receipt = find_receipt_by_no(str(receipt_no)) if receipt_no else None
    if receipt and receipt.get("kind") == "claim" and receipt.get("granted"):
        return receipt

    # 兼容没有回执但已经通过通用动作进入执行中的旧数据/测试。
    if task.get("status") == "执行中" and task.get("执行人员"):
        return {
            "kind": "claim",
            "granted": True,
            "receipt_no": str(receipt_no or ""),
            "task_id": task.get("id"),
            "claimant": task.get("执行人员"),
            "legacy": True,
            "operation_seq": int(task.get("claim_seq") or 0),
        }
    return None


def make_review_item(
    *,
    task: dict[str, Any],
    claim_receipt: dict[str, Any] | None,
    objection_receipt: dict[str, Any] | None,
    submission: str,
    submitted_by: str,
    request_id: str = "",
) -> dict[str, Any]:
    """创建或返回同一次认领+异议+提交对应的唯一待复核事项。"""
    reviews = store.rows(REVIEW_TABLE)
    claim_no = str((claim_receipt or {}).get("receipt_no") or task.get("claim_receipt_no") or "")
    objection_no = str((objection_receipt or {}).get("receipt_no") or task.get("objection_receipt_no") or "")

    if request_id:
        for review in reviews:
            if review.get("request_id") == request_id:
                return review

    for review in reviews:
        if review.get("task_id") != task.get("id"):
            continue
        if claim_no and review.get("claim_receipt_no") != claim_no:
            continue
        if objection_no and review.get("objection_receipt_no") != objection_no:
            continue
        if review.get("status") == "待复核":
            return review

    review = {
        "id": next_row_id(REVIEW_TABLE),
        "review_no": f"ZF-FH-{task_number(task)}-{next_row_id(REVIEW_TABLE):04d}",
        "kind": "诊改待复核事项",
        "task_id": task.get("id"),
        "task_number": task_number(task),
        "meeting_id": (objection_receipt or {}).get("meeting_id") or source_meeting_id(task),
        "meeting_number": (objection_receipt or {}).get("meeting_number", ""),
        "resolution_index": (objection_receipt or {}).get("resolution_index"),
        "resolution_code": (objection_receipt or {}).get("resolution_code", ""),
        "resolution_entry": (objection_receipt or {}).get("resolution_entry", ""),
        "claim_request_id": (claim_receipt or {}).get("request_id", ""),
        "claim_receipt_no": claim_no,
        "objection_receipt_no": objection_no,
        "submission": submission,
        "submitted_by": submitted_by,
        "status": "待复核",
        "request_id": request_id,
        "operation_seq": store.next_operation_seq(),
    }
    reviews.append(review)

    task["review_item_id"] = review["id"]
    task["review_no"] = review["review_no"]
    task["pending"] = True

    meeting_id = (objection_receipt or {}).get("meeting_id")
    if meeting_id:
        meeting = store.find("review_meeting", int(meeting_id))
        if meeting is not None:
            meeting.setdefault("review_item_nos", [])
            if review["review_no"] not in meeting["review_item_nos"]:
                meeting["review_item_nos"].append(review["review_no"])
            meeting["review_no"] = review["review_no"]
            code = str((objection_receipt or {}).get("resolution_code") or "")
            index = (objection_receipt or {}).get("resolution_index")
            state_key = code or str(index)
            states = meeting.setdefault("resolution_states", {})
            state = states.setdefault(state_key, {})
            state["review_no"] = review["review_no"]
            state["status"] = "已生成诊改待复核事项"

    if objection_receipt is not None:
        objection_receipt["review_item_id"] = review["id"]
        objection_receipt["review_no"] = review["review_no"]
        objection_receipt["handling_result"] = "原认领有效，成果已随原认领送交诊改复核"
    if claim_receipt is not None:
        claim_receipt["review_item_id"] = review["id"]
        claim_receipt["review_no"] = review["review_no"]
    return review


def receipt_lookup(reference: str) -> dict[str, Any] | None:
    receipt = find_receipt_by_no(reference)
    if receipt:
        return receipt
    review = None
    for item in store.rows(REVIEW_TABLE):
        if str(item.get("review_no", "")).casefold() == str(reference).casefold():
            review = item
            break
        if str(item.get("request_id", "")) == str(reference):
            review = item
            break
    if review:
        return {
            "receipt_type": "待复核事项回执",
            "receipt_no": review.get("review_no"),
            "review_no": review.get("review_no"),
            "review_item": review,
            "task_id": review.get("task_id"),
            "task_number": review.get("task_number"),
            "original_result": "成果已提交，当前为待复核",
        }
    return None
