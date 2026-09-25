"""保险与理赔备案业务规则：赔付上限口径、重复报案识别、草稿续填与幂等提交都收在这里。

口径约定（只此一份，路由层不做业务判断）：
- 赔付上限 = 资产原值 × 设备类型赔付比例，以出险时适用的保单为准；
- 保单口径赔付 = min(定损金额, 赔付上限)；
- 同一设备在同一张保单（同一个保险期间）内只认第一条正式报案，后续报案标「疑似重复」；
- 跨保单（跨保险期间）的报案各自独立，金额不合并。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "insurance"
ASSET_MODULE = "insurance_asset"
POLICY_MODULE = "insurance_policy"

STATUS_DRAFT = "草稿"
STATUS_REPORTED = "已报案"
STATUS_PAID = "已赔付"
STATUS_ORDER = [STATUS_DRAFT, STATUS_REPORTED, STATUS_PAID]

# 登记/提交时必须齐备的理赔材料；不齐只能存草稿。
MATERIAL_FIELDS = ["事故照片", "检修报告", "报案回执", "损失发票", "责任说明"]
REQUIRED_FIELDS = ["设备编号", "出险时间", "定损金额", "申报赔付金额"]

# 设备类型 -> 赔付比例（占资产原值），未列名的类型按兜底比例走。
EQUIPMENT_RATES = {
    "逆变器": 0.80,
    "汇流箱": 0.70,
    "组串/组件": 0.60,
    "支架": 0.50,
    "监控设备": 0.60,
    "升压变": 0.80,
    "其他": 0.50,
}

# 记录里由后端核算并固化的快照字段：列表与详情共用，避免两处口径不一致。
SNAPSHOT_FIELDS = [
    "设备类型", "设备名称", "资产原值", "保单号", "保险起期", "保险止期",
    "赔付比例", "赔付上限", "保单口径赔付",
]

MONEY_TOLERANCE = 0.01


def _to_money(value: Any) -> float | None:
    """把前端入参转成两位小数金额；空值/非数字返回 None，由调用方决定怎么提示。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        money = float(value)
    except (TypeError, ValueError):
        return None
    return round(money, 2)


class InsuranceService:
    # ---------- 基础目录 ----------

    def options(self) -> dict[str, Any]:
        """设备资产与保单选项：供登记弹窗下拉，实际赔付口径仍以 quote 接口为准。"""
        devices = [
            {
                "设备编号": row.get("设备编号"),
                "设备名称": row.get("设备名称"),
                "设备类型": row.get("设备类型"),
                "资产原值": row.get("资产原值"),
            }
            for row in store.rows(ASSET_MODULE)
        ]
        policies = [
            {
                "保单号": row.get("保单号"),
                "设备编号": row.get("设备编号"),
                "保险起期": row.get("保险起期"),
                "保险止期": row.get("保险止期"),
            }
            for row in store.rows(POLICY_MODULE)
        ]
        return {"devices": devices, "policies": policies}

    def _find_asset(self, device_id: str) -> dict[str, Any] | None:
        for row in store.rows(ASSET_MODULE):
            if str(row.get("设备编号", "")) == device_id:
                return row
        return None

    def _find_policy(self, device_id: str, loss_date: str) -> dict[str, Any] | None:
        """按出险日期落在保险期间内找保单；日期是 YYYY-MM-DD，可直接按字符串比较。"""
        for row in store.rows(POLICY_MODULE):
            if str(row.get("设备编号", "")) != device_id:
                continue
            if row.get("保险起期") <= loss_date <= row.get("保险止期"):
                return row
        return None

    def quote(self, device_id: str | None, loss_date: str | None) -> tuple[dict[str, Any] | None, str]:
        """按设备与出险日期核算赔付口径；找不到资产或保单时返回可读原因。"""
        device_id = str(device_id or "").strip()
        loss_date = str(loss_date or "").strip()
        if not device_id:
            return None, "请先选择设备"
        if not loss_date:
            return None, "请先选择出险日期"
        asset = self._find_asset(device_id)
        if asset is None:
            return None, f"设备 {device_id} 不在资产目录里"
        policy = self._find_policy(device_id, loss_date)
        if policy is None:
            return None, f"设备 {device_id} 在 {loss_date} 没有处于保险期间内的保单"
        device_type = str(asset.get("设备类型", "其他"))
        rate = EQUIPMENT_RATES.get(device_type, EQUIPMENT_RATES["其他"])
        asset_value = round(float(asset["资产原值"]), 2)
        return {
            "设备编号": device_id,
            "设备名称": asset.get("设备名称"),
            "设备类型": device_type,
            "资产原值": asset_value,
            "赔付比例": rate,
            "保单号": policy.get("保单号"),
            "保险起期": policy.get("保险起期"),
            "保险止期": policy.get("保险止期"),
            "赔付上限": round(asset_value * rate, 2),
        }, ""

    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        duplicate: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("理赔报案号", ""))
                or keyword in str(row.get("设备编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if duplicate in ("true", "True", "1", "是"):
            rows = [row for row in rows if row.get("疑似重复")]
        elif duplicate in ("false", "False", "0", "否"):
            rows = [row for row in rows if not row.get("疑似重复")]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 登记 / 草稿 / 提交 ----------

    def _find_by_token(self, client_token: str) -> dict[str, Any] | None:
        if not client_token:
            return None
        for row in store.rows(MODULE):
            if row.get("client_token") == client_token:
                return row
        return None

    def _next_serial(self, prefix: str) -> str:
        """按年报案号/草稿号取序列，年份按当前自然年。"""
        year = date.today().year
        head = f"{prefix}-{year}-"
        serials = [
            int(str(row.get("理赔报案号", ""))[len(head):])
            for row in store.rows(MODULE)
            if str(row.get("理赔报案号", "")).startswith(head)
        ]
        return f"{head}{max(serials, default=0) + 1:04d}"

    def _base_snapshot(self, quote_info: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = {field: None for field in SNAPSHOT_FIELDS}
        if quote_info:
            snapshot.update({field: quote_info.get(field) for field in SNAPSHOT_FIELDS if field != "保单口径赔付"})
        return snapshot

    def _apply_values(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        """把表单字段合并进记录；材料勾选项与文本字段分开处理。"""
        text_fields = [
            "设备编号", "出险时间", "报案时间", "超上限依据", "缺件说明",
        ]
        for field in text_fields:
            if field in values:
                entry[field] = values.get(field)
        for field in MATERIAL_FIELDS:
            if field in values:
                entry[field] = bool(values.get(field))
        for field in ("定损金额", "申报赔付金额"):
            if field in values:
                entry[field] = _to_money(values.get(field))

    def _save_as_draft(
        self,
        entry: dict[str, Any] | None,
        values: dict[str, Any],
        quote_info: dict[str, Any] | None,
        reason: str,
    ) -> tuple[dict[str, Any], bool, str]:
        """校验没过时统一落草稿，保证用户补完材料能接着填、数据不丢。"""
        created = entry is None
        if entry is None:
            entry = {"id": self._next_id(), "client_token": values.get("client_token")}
            entry.update(self._base_snapshot(quote_info))
            for field in MATERIAL_FIELDS:
                entry[field] = False
            store.rows(MODULE).append(entry)
        if quote_info:
            entry.update({field: quote_info.get(field) for field in SNAPSHOT_FIELDS if field != "保单口径赔付"})
        self._apply_values(entry, values)
        self._refresh_materials(entry)
        entry["status"] = STATUS_DRAFT
        entry["pending"] = True
        entry.setdefault("理赔报案号", self._next_serial("DRA"))
        entry.setdefault("是否认账", True)
        entry.setdefault("疑似重复", False)
        entry.setdefault("口径不符", False)
        entry.setdefault("重复报案号", None)
        entry.setdefault("超上限依据", None)
        entry["abnormal"] = False
        prefix = "草稿已保存" if created else "草稿已更新"
        return entry, False, f"{prefix}：{reason}，补齐后可继续提交"

    def _next_id(self) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(MODULE)), default=0) + 1

    def _refresh_materials(self, entry: dict[str, Any]) -> None:
        missing = [field for field in MATERIAL_FIELDS if not entry.get(field)]
        entry["材料齐全"] = not missing
        entry["缺件说明"] = "、".join(missing) if missing else None

    def save_claim(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, bool, str]:
        """草稿保存或正式提交的统一入口，按 values['mode'] 区分。

        始终带 client_token：同一 token 重入是同一条记录，提交重试不会产生两条赔付。
        """
        mode = str(values.get("mode") or "draft").strip()
        client_token = str(values.get("client_token") or "").strip()
        if not client_token:
            return None, False, "缺少提交凭证 client_token，无法保证重复提交安全"

        existing = self._find_by_token(client_token)
        # 已正式报案/赔付后再次提交：幂等返回既有记录，绝不新增第二条。
        if existing is not None and existing.get("status") != STATUS_DRAFT:
            return existing, True, f"该报案已提交（{existing.get('理赔报案号')}），未重复生成记录"

        # 草稿按 id 或 token 都能定位回同一条：首次保存草稿若请求超时，
        # 前端重试即便换了凭证，凭草稿 id 仍是更新而不是新增。
        if existing is None and values.get("id") is not None:
            by_id = store.find(MODULE, int(values["id"]))
            if by_id is not None and by_id.get("status") == STATUS_DRAFT:
                existing = by_id
                existing["client_token"] = client_token

        quote_info, quote_error = self.quote(values.get("设备编号"), values.get("出险时间"))

        if mode == "draft":
            entry, _ok, _message = self._save_as_draft(existing, values, quote_info, "材料待补充")
            if quote_error:
                return entry, True, f"草稿已保存：当前口径暂无法核算（{quote_error}），补齐后可继续提交"
            loss_amount = entry.get("定损金额")
            if isinstance(loss_amount, (int, float)):
                entry["保单口径赔付"] = round(min(loss_amount, quote_info["赔付上限"]), 2)
            return entry, True, "草稿已保存，可随时继续补充材料后提交"

        # ---------- 正式提交：逐项校验，没过的一律保留为草稿 ----------

        missing_basic = [
            field for field in REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing_basic:
            entry, _ok, message = self._save_as_draft(existing, values, quote_info, f"缺少必填项：{'、'.join(missing_basic)}")
            return entry, False, message

        loss_amount = _to_money(values.get("定损金额"))
        claim_amount = _to_money(values.get("申报赔付金额"))
        if loss_amount is None or claim_amount is None:
            entry, _ok, message = self._save_as_draft(existing, values, quote_info, "定损金额或申报赔付金额不是有效数字")
            return entry, False, message
        if loss_amount < 0 or claim_amount < 0:
            entry, _ok, message = self._save_as_draft(existing, values, quote_info, "赔付金额不能为负数")
            return entry, False, message

        if quote_error:
            entry, _ok, message = self._save_as_draft(existing, values, None, quote_error)
            return entry, False, message

        missing_materials = [field for field in MATERIAL_FIELDS if not bool(values.get(field))]
        if missing_materials:
            entry, _ok, message = self._save_as_draft(
                existing, values, quote_info, f"理赔材料不全（缺：{'、'.join(missing_materials)}）"
            )
            return entry, False, message

        over_limit_basis = str(values.get("超上限依据") or "").strip()
        payout_limit = quote_info["赔付上限"]
        if claim_amount > payout_limit + MONEY_TOLERANCE and not over_limit_basis:
            entry, _ok, message = self._save_as_draft(
                existing, values, quote_info,
                f"申报赔付 ¥{claim_amount:.2f} 超过赔付上限 ¥{payout_limit:.2f}，必须写明超上限依据",
            )
            return entry, False, message

        # ---------- 全部通过：落正式报案 ----------

        reference_payout = round(min(loss_amount, payout_limit), 2)
        if existing is None:
            entry = {"id": self._next_id(), "client_token": client_token}
            store.rows(MODULE).append(entry)
        else:
            entry = existing
        entry.update({field: quote_info.get(field) for field in SNAPSHOT_FIELDS if field != "保单口径赔付"})
        entry["保单口径赔付"] = reference_payout
        self._apply_values(entry, values)
        entry["超上限依据"] = over_limit_basis or None
        self._refresh_materials(entry)
        entry["理赔报案号"] = self._next_serial("CLM")
        entry["报案时间"] = str(values.get("报案时间") or date.today().isoformat())
        entry["status"] = STATUS_REPORTED
        entry["pending"] = True

        # 同一保险期间（同设备同保单）只认第一条正式报案，后续标疑似重复。
        first = self._find_first_report(entry["设备编号"], entry["保单号"], exclude_id=int(entry["id"]))
        if first is not None:
            entry["是否认账"] = False
            entry["疑似重复"] = True
            entry["重复报案号"] = first.get("理赔报案号")
            duplicate_note = f"；同一保险期内已有报案 {first.get('理赔报案号')}，只认第一条，本条标记疑似重复"
        else:
            entry["是否认账"] = True
            entry["疑似重复"] = False
            entry["重复报案号"] = None
            duplicate_note = ""

        mismatch = abs(claim_amount - reference_payout) > MONEY_TOLERANCE
        entry["口径不符"] = mismatch
        entry["abnormal"] = bool(entry["疑似重复"] or mismatch)

        if mismatch:
            warn = f"申报赔付 ¥{claim_amount:.2f} 与保单口径应赔 ¥{reference_payout:.2f} 不一致，请核对保单赔付口径"
        else:
            warn = ""
        return entry, True, f"理赔报案已登记（{entry['理赔报案号']}）{duplicate_note}{warn}".strip()

    def _find_first_report(
        self, device_id: str, policy_no: str, *, exclude_id: int
    ) -> dict[str, Any] | None:
        candidates = [
            row for row in store.rows(MODULE)
            if int(row.get("id", 0)) != exclude_id
            and row.get("设备编号") == device_id
            and row.get("保单号") == policy_no
            and row.get("status") in (STATUS_REPORTED, STATUS_PAID)
        ]
        return min(candidates, key=lambda row: int(row.get("id", 0)), default=None)

    # ---------- 状态动作 ----------

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"理赔记录 {entry_id} 不存在或已归档"
        if action != "确认赔付":
            return None, f"动作「{action}」不属于保险理赔可执行范围"
        if entry.get("status") != STATUS_REPORTED:
            return None, f"当前状态为「{entry.get('status')}」，只有已报案案件可以确认赔付"
        if not entry.get("是否认账", True):
            return None, f"{entry.get('理赔报案号')} 为疑似重复报案，同一保险期只认第一条，不能确认赔付"
        entry["status"] = STATUS_PAID
        entry["pending"] = False
        return entry, f"{entry.get('理赔报案号')} 已确认赔付 ¥{float(entry.get('申报赔付金额', 0)):.2f}"
