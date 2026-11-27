"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    receipts: list[dict[str, Any]] | None = None
    review_item: dict[str, Any] | None = None
    conflict: dict[str, Any] | None = None
    idempotent_replay: bool = False


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str
    remark: str | None = None
    request_id: str | None = None
    operator: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    resolution_index: int | str | None = None
    resolution_code: str | None = None
    resolution_entry: str | None = None
    objection_receipt_no: str | None = None
    claim_receipt_no: str | None = None
    submission: str | None = None
    result_content: str | None = None
