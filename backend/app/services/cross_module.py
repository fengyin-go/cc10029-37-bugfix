"""跨模块查询和校验辅助函数。

为每个业务模块提供跨模块的数据完整性验证、状态联动、
幂等性和冲突检测能力。
"""
from __future__ import annotations

from typing import Any

from app.store import store


def find_by_module_and_id(module: str, entry_id: int) -> dict[str, Any] | None:
    """通用的跨模块实体查找。"""
    return store.find(module, entry_id)


def require_entity(module: str, entry_id: int, context: str) -> dict[str, Any]:
    """查找并验证实体存在，否则抛出带模块上下文的异常。"""
    entry = store.find(module, entry_id)
    if entry is None:
        raise ValueError(f"跨模块校验失败：{context}引用的{module} #{entry_id} 不存在")
    return entry


def find_by_field(
    module: str, field: str, value: str | None
) -> list[dict[str, Any]]:
    """按字段值在指定模块中搜索所有匹配记录。"""
    if value is None:
        return []
    rows = store.rows(module)
    return [
        row for row in rows
        if str(row.get(field, "")).casefold() == value.casefold()
    ]


def check_entity_status(
    module: str, entry_id: int, allowed_statuses: list[str], context: str
) -> dict[str, Any]:
    """验证实体状态在允许范围内。"""
    entry = require_entity(module, entry_id, context)
    current = entry.get("status", "")
    if current not in allowed_statuses:
        raise ValueError(
            f"跨模块校验失败：{context}要求{module} #{entry_id} 状态为{'/'.join(allowed_statuses)}，"
            f"当前状态为'{current}'"
        )
    return entry


def has_any_entry_in_status(module: str, statuses: list[str]) -> bool:
    """检查模块中是否有任何记录处于指定状态。"""
    return any(
        row.get("status") in statuses
        for row in store.rows(module)
    )


def count_by_field_value(module: str, field: str, value: str) -> int:
    """统计模块中指定字段匹配的记录数。"""
    return sum(
        1 for row in store.rows(module)
        if str(row.get(field, "")).casefold() == value.casefold()
    )


def module_snapshot(module: str) -> dict[str, Any]:
    """获取模块的数据快照。"""
    rows = store.rows(module)
    return {
        "module": module,
        "count": len(rows),
        "pending": sum(1 for r in rows if r.get("pending")),
        "abnormal": sum(1 for r in rows if r.get("abnormal")),
    }