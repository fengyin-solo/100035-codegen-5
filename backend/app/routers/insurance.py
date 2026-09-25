"""保险与理赔备案接口：设备台账、保单取数与理赔单的登记、草稿、口径校验、状态流转。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.insurance import InsuranceService

router = APIRouter(prefix="/api/insurance", tags=["保险与理赔备案"])

service = InsuranceService()

LIST_FIELDS = [
    "理赔单号", "保单号", "设备编号", "设备类型", "报案日期",
    "出险原因", "赔付金额", "赔付上限", "状态",
]
STATUSES = ["草稿", "已提交", "已认赔", "已拒赔", "已撤"]


# 资产台账/保单/试算放在 "/{entry_id}" 之前，避免被数字路径吞掉。
@router.get("/assets", response_model=dict)
def list_assets(
    keyword: str | None = Query(default=None, description="按设备编号或设备类型检索"),
) -> dict[str, Any]:
    """资产台账：登记理赔时选设备用，返回资产原值与按类型算出的赔付上限。"""
    return {"items": service.list_assets(keyword)}


@router.get("/policies", response_model=dict)
def list_policies(
    device: str | None = Query(default=None, description="按设备编号过滤其名下保单"),
) -> dict[str, Any]:
    """保单清单：选择保单后带出保险期与单案赔付限额。"""
    return {"items": service.list_policies(device)}


@router.get("/quote", response_model=ActionResult)
def quote(
    device: str = Query(description="设备编号"),
    policy: str | None = Query(default=None, description="保单号（可选）"),
    payout: str | None = Query(default=None, description="拟赔付金额（可选，试算超限）"),
) -> ActionResult:
    """按设备类型与资产原值试算赔付上限，并核对保单口径，给登记表单自动带出数字。"""
    view, error = service.quote(device, policy, payout)
    if view is None:
        return ActionResult(ok=False, message=error or "无法试算赔付上限")
    warnings = list(view.get("口径提示", [])) if isinstance(view, dict) else []
    return ActionResult(ok=True, message="赔付上限试算完成", entry=view, warnings=warnings)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按理赔单号检索"),
    status: str | None = Query(default=None, description="草稿、已提交、已认赔、已拒赔、已撤"),
    duplicate: bool = Query(default=False, description="只看疑似重复报案"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按理赔单号、状态与疑似重复标记过滤理赔列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, duplicate_only=duplicate, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条理赔明细；赔付上限与列表同一取数口径，保证数字一致。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"理赔单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记理赔单。

    values.draft=true 时保存草稿（材料不全也保留，可接着填）；
    默认按正式报案校验：超赔付标准上限必须填超限依据；
    values.request_token 用于提交失败后的重试幂等，重复 token 不会生成第二条。
    """
    values = dict(payload.values)
    as_draft = bool(values.pop("draft", False))
    entry, message, warnings = service.create_entry(values, as_draft=as_draft)
    if entry is None:
        return ActionResult(ok=False, message=message, warnings=warnings)
    return ActionResult(ok=True, message=message, entry=entry, warnings=warnings)


@router.put("/{entry_id}", response_model=ActionResult)
def update_draft(entry_id: int, payload: EntryPayload) -> ActionResult:
    """在草稿上继续补材料；只有草稿可编辑，避免改动已报案口径。"""
    entry, message, warnings = service.update_draft(entry_id, dict(payload.values))
    if entry is None:
        return ActionResult(ok=False, message=message, warnings=warnings)
    return ActionResult(ok=True, message=message, entry=entry, warnings=warnings)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行提交报案、认赔、拒赔、撤案；疑似重复的报案认赔会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message, warnings = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message, warnings=warnings)
    return ActionResult(ok=True, message=message, entry=entry, warnings=warnings)


@router.get("/export/all")
def export_entries() -> dict[str, Any]:
    """导出理赔备案清单：全量数据，赔付上限与列表/详情同口径。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "insurance", "total": total, "items": items}
