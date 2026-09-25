"""保险与理赔备案接口：设备/保单选项、赔付口径试算、理赔登记与确认赔付。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.insurance import InsuranceService

router = APIRouter(prefix="/api/insurance", tags=["保险与理赔"])

service = InsuranceService()

LIST_FIELDS = [
    "理赔报案号", "设备编号", "设备类型", "设备名称", "出险时间", "保单号",
    "资产原值", "赔付上限", "定损金额", "申报赔付金额", "保单口径赔付",
    "材料齐全", "是否认账", "status",
]
STATUSES = ["草稿", "已报案", "已赔付"]
MATERIAL_FIELDS = ["事故照片", "检修报告", "报案回执", "损失发票", "责任说明"]


@router.get("/options")
def options() -> dict[str, Any]:
    """登记弹窗需要的设备资产与保单选项。"""
    return service.options()


@router.get("/quote")
def quote(
    device_id: str = Query(..., description="设备编号"),
    loss_date: str = Query(..., description="出险日期 YYYY-MM-DD"),
) -> dict[str, Any]:
    """按设备类型与资产原值核算赔付上限及保单口径，登记页据此自动带出。"""
    info, error = service.quote(device_id, loss_date)
    if info is None:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True, "quote": info}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按理赔报案号或设备编号检索"),
    status: str | None = Query(default=None, description="草稿、已报案、已赔付"),
    duplicate: str | None = Query(default=None, description="true=仅看疑似重复"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按报案号、状态、疑似重复标记过滤理赔列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, duplicate=duplicate, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条理赔明细，赔付上限等口径字段与列表行同源同值。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"理赔记录 {entry_id} 不存在或已归档")
    return entry


@router.post("/claims", response_model=ActionResult)
def save_claim(payload: EntryPayload) -> ActionResult:
    """保存草稿或正式提交报案，靠 client_token 幂等，重试不会出现两条赔付记录。"""
    entry, ok, message = service.save_claim(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=ok, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对已报案且认账的理赔执行确认赔付；草稿、疑似重复案件会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export/data")
def export_entries() -> dict[str, Any]:
    """导出保险理赔清单：返回当前数据的全量快照。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "insurance", "total": total, "items": items}
