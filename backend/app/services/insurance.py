"""保险与理赔备案业务规则。

口径约定（列表与详情共用本模块的 `present`，保证两边赔付上限完全一致）：

- 赔付上限（赔付标准上限）= 设备资产原值 × 设备类型赔付比例，取数来自资产台账
  ``insurance_asset``，保单只用于校验保险期与单案赔付限额。
- 赔付金额超过赔付标准上限时，必须填写「超限依据」，否则不允许保存为正式报案；
  保存草稿不受此限（材料不全先存草稿，回来接着填）。
- 赔付金额超过保单单案赔付限额属于「与保单口径对不上」，只做非阻断提示，需人工复核。
- 同一台设备在同一份保单（同一保险期）内报案两次及以上时，只认报案日期最早的一条，
  其余在列表中标「疑似重复」且不允许认赔；跨保单期（不同保单号）报案可以并存，
  各自主张赔付，系统不合并金额（任何地方都不按设备汇总赔付金额）。
- 提交支持 request_token 幂等：网络失败重试时服务端识别同一 token，直接返回原记录，
  不会产生第二条赔付记录。

状态流转只允许在本模块内发生，路由层不做业务判断。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "insurance"
ASSET_MODULE = "insurance_asset"
POLICY_MODULE = "insurance_policy"

# 理赔单上需要落库的字段；草稿也按这套字段存，缺料只体现在状态与校验上。
FORM_FIELDS = [
    "理赔单号", "保单号", "设备编号", "设备类型", "资产原值", "报案日期",
    "出险原因", "赔付金额", "超限依据", "材料清单",
]
# 正式报案（提交）时缺一不可的字段；材料不全只能先存草稿。
REQUIRED_FIELDS = ["保单号", "设备编号", "报案日期", "出险原因", "赔付金额", "材料清单"]

STATUS_ORDER = ["草稿", "已提交", "已认赔", "已拒赔", "已撤"]
# 认赔/拒赔是终态前的处理动作；撤案后同一保险期再报案按新单处理。
ACTION_RULES = {"提交报案": "已提交", "认赔": "已认赔", "拒赔": "已拒赔", "撤案": "已撤"}
FINAL_STATUSES = {"已认赔", "已拒赔", "已撤"}

# 设备类型赔付比例：赔付上限 = 资产原值 × 比例。新增设备类型时在这里补一行即可。
PAYOUT_RATIO: dict[str, float] = {
    "逆变器": 0.8,
    "汇流箱": 0.7,
    "组串": 0.6,
    "跟踪支架": 0.5,
    "箱变": 0.9,
}
DEFAULT_RATIO = 0.3

# 参与同一保险期重复报案判定的状态：草稿和已撤的单子不占位。
DUPLICATE_CANDIDATE_STATUSES = {"已提交", "已认赔", "已拒赔"}


def _to_amount(value: Any) -> float | None:
    """把表单里的金额统一成 float；空值/非数字返回 None，由调用方决定是否报错。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    try:
        return round(float(str(value).replace(",", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    """兼容 '2026-09-01' 与 '2026-09-01 10:00:00' 两种填法。"""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


class InsuranceService:
    # ---- 台账/保单取数 --------------------------------------------------

    def list_assets(self, keyword: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(ASSET_MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("设备编号", "")) or keyword in str(row.get("设备类型", ""))
            ]
        return [self._asset_view(row) for row in rows]

    def list_policies(self, device_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(POLICY_MODULE)
        if device_code:
            rows = [row for row in rows if row.get("设备编号") == device_code]
        return [dict(row) for row in rows]

    def _find_asset(self, device_code: str) -> dict[str, Any] | None:
        for row in store.rows(ASSET_MODULE):
            if str(row.get("设备编号", "")).strip() == str(device_code).strip():
                return row
        return None

    def _find_policy(self, policy_no: str) -> dict[str, Any] | None:
        for row in store.rows(POLICY_MODULE):
            if str(row.get("保单号", "")).strip() == str(policy_no).strip():
                return row
        return None

    def _ratio(self, device_type: Any) -> float:
        return PAYOUT_RATIO.get(str(device_type or "").strip(), DEFAULT_RATIO)

    def _asset_view(self, asset: dict[str, Any]) -> dict[str, Any]:
        """登记页选择设备后自动带出的内容，赔付上限与列表/详情同一公式。"""
        original = _to_amount(asset.get("资产原值")) or 0.0
        ratio = self._ratio(asset.get("设备类型"))
        return {
            "设备编号": asset.get("设备编号"),
            "设备类型": asset.get("设备类型"),
            "设备名称": asset.get("设备名称"),
            "资产原值": original,
            "赔付比例": ratio,
            "赔付上限": round(original * ratio, 2),
        }

    def quote(
        self, device_code: str, policy_no: str | None = None, payout: Any = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """试算赔付上限与保单口径，给登记表单实时带出数字。"""
        asset = self._find_asset(device_code)
        if asset is None:
            return None, f"设备 {device_code} 不在资产台账里，无法核定赔付上限"
        view = self._asset_view(asset)
        policy = self._find_policy(policy_no) if policy_no else None
        if policy_no and policy is None:
            return None, f"保单 {policy_no} 不存在，请先核对保单号"
        if policy is not None:
            if str(policy.get("设备编号")) != str(device_code).strip():
                return None, f"保单 {policy_no} 承保设备不是 {device_code}"
            policy_cap = _to_amount(policy.get("单案赔付限额"))
            view.update({
                "保单号": policy.get("保单号"),
                "保险起期": policy.get("保险起期"),
                "保险止期": policy.get("保险止期"),
                "保单赔付限额": policy_cap,
            })
        payout_amount = _to_amount(payout)
        if payout_amount is not None:
            view["拟赔付金额"] = payout_amount
            view["超赔付标准上限"] = payout_amount > view["赔付上限"]
            if policy is not None:
                view["超保单限额"] = (
                    policy_cap is not None and payout_amount > policy_cap
                )
        return view, None

    # ---- 列表与详情 -----------------------------------------------------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        duplicate_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self._mark_duplicate_flags()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("理赔单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if duplicate_only:
            rows = [row for row in rows if self._is_duplicate(row)]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        return [self.present(row) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        self._mark_duplicate_flags()
        entry = store.find(MODULE, entry_id)
        return self.present(entry) if entry is not None else None

    def present(self, row: dict[str, Any]) -> dict[str, Any]:
        """把存储行补充成列表/详情统一的展示结构。

        赔付上限在这里按台账实时计算，列表接口与详情接口都走这里，
        因此「列表里的赔付上限」和「详情页的数字」必然是同一个值。
        """
        entry = dict(row)
        is_duplicate = self._is_duplicate(entry)
        is_first = bool(entry.get("_recognized")) and not is_duplicate
        entry.pop("_recognized", None)
        entry.pop("_duplicate", None)
        device_code = str(entry.get("设备编号") or "").strip()
        asset = self._find_asset(device_code) if device_code else None
        if asset is not None:
            # 以台账为准带出类型与原值，防止手填导致上限口径漂移。
            entry["设备类型"] = asset.get("设备类型")
            entry["资产原值"] = _to_amount(asset.get("资产原值"))
            entry["设备名称"] = asset.get("设备名称")
        original = _to_amount(entry.get("资产原值")) or 0.0
        ratio = self._ratio(entry.get("设备类型"))
        cap = round(original * ratio, 2)
        entry["赔付比例"] = ratio
        entry["赔付上限"] = cap

        policy = self._find_policy(str(entry.get("保单号") or "")) if entry.get("保单号") else None
        policy_cap: float | None = None
        if policy is not None:
            policy_cap = _to_amount(policy.get("单案赔付限额"))
            entry.setdefault("保险起期", policy.get("保险起期"))
            entry["保险起期"] = policy.get("保险起期")
            entry["保险止期"] = policy.get("保险止期")
            entry["保单赔付限额"] = policy_cap
        entry["疑似重复"] = is_duplicate
        entry["首条认可"] = is_first

        payout = _to_amount(entry.get("赔付金额"))
        entry["超赔付标准上限"] = payout is not None and payout > cap
        warnings: list[str] = []
        if payout is not None and payout > cap and not str(entry.get("超限依据") or "").strip():
            warnings.append(f"赔付金额 {payout:.2f} 已超过赔付标准上限 {cap:.2f}，须补充超限依据")
        if payout is not None and policy_cap is not None and payout > policy_cap:
            warnings.append(
                f"赔付金额 {payout:.2f} 高于保单单案赔付限额 {policy_cap:.2f}，与保单口径不一致，请复核"
            )
        if entry["疑似重复"]:
            warnings.append("同一保险期内该设备已有更早报案，按口径只认第一条，本单疑似重复")
        entry["口径提示"] = warnings
        return entry

    # ---- 登记 / 草稿 / 提交 ---------------------------------------------

    def find_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        for row in store.rows(MODULE):
            if str(row.get("request_token") or "") == token:
                return row
        return None

    def create_entry(
        self, values: dict[str, Any], *, as_draft: bool
    ) -> tuple[dict[str, Any] | None, str, list[str]]:
        """登记理赔单。

        草稿（as_draft=True）：材料不全也保留，后续可改可提交。
        正式（as_draft=False）：跑完整口径校验，超限必须附依据。
        返回 (entry, message, warnings)；entry 为 None 时 message 是阻断原因。
        """
        token = str(values.get("request_token") or "").strip()
        existing = self.find_by_token(token)
        if existing is not None:
            # 提交没成功时前端会拿同一个 token 再试一次：直接认回原记录，杜绝重复两条。
            self._mark_duplicate_flags()
            return self.present(existing), "该报案已登记，已返回原记录，未重复生成", []

        normalized, errors, warnings = self._normalize(values, submit=not as_draft)
        if errors:
            return None, "；".join(errors), warnings

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: normalized.get(field) for field in FORM_FIELDS})
        if not str(entry.get("理赔单号") or "").strip():
            entry["理赔单号"] = f"CLM-{entry['id']:04d}"
        entry["request_token"] = token
        entry["status"] = "草稿" if as_draft else "已提交"
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        self._mark_duplicate_flags()
        message = "理赔草稿已保存，可继续补充材料后提交" if as_draft else "理赔报案已提交"
        return self.present(entry), message, warnings

    def update_draft(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, list[str]]:
        """在草稿上接着填：只允许改草稿，正式单需走撤案后重报。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"理赔单 {entry_id} 不存在或已归档", []
        if entry.get("status") != "草稿":
            return None, "只有草稿状态的理赔单可以继续编辑", []
        for field in FORM_FIELDS:
            if field in values:
                entry[field] = values[field]
        # 金额/类型归一化，保持与正式提交同口径；草稿不强制校验完整性。
        normalized, _errors, warnings = self._normalize(entry, submit=False)
        for field in ("设备类型", "资产原值", "赔付金额"):
            entry[field] = normalized.get(field)
        self._mark_duplicate_flags()
        return self.present(entry), "草稿已更新", warnings

    def run_action(
        self, entry_id: int, action: str
    ) -> tuple[dict[str, Any] | None, str, list[str]]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"理赔单 {entry_id} 不存在或已归档", []
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于保险理赔可执行范围", []

        if action == "提交报案":
            if entry.get("status") != "草稿":
                return None, "只有草稿可以提交报案", []
            normalized, errors, warnings = self._normalize(entry, submit=True)
            if errors:
                return None, "；".join(errors), warnings
            for field in FORM_FIELDS:
                entry[field] = normalized.get(field)
        else:
            warnings: list[str] = []
            status = entry.get("status")
            if action == "认赔":
                if status != "已提交":
                    return None, "只有已提交的报案可以认赔", []
                self._mark_duplicate_flags()
                if self._is_duplicate(entry):
                    first = self._first_recognized(entry)
                    first_no = first.get("理赔单号") if first else "首条报案"
                    return None, f"同一保险期内已认最早报案 {first_no}，本单疑似重复，不予认赔", []
            elif action == "拒赔":
                if status != "已提交":
                    return None, "只有已提交的报案可以拒赔", []
            elif action == "撤案":
                if status not in ("草稿", "已提交"):
                    return None, "当前状态不允许撤案", []

        entry["status"] = ACTION_RULES[action]
        entry["pending"] = entry["status"] not in FINAL_STATUSES
        self._mark_duplicate_flags()
        presented = self.present(entry)
        entry["abnormal"] = bool(presented.get("疑似重复") or presented.get("口径提示"))
        return presented, f"理赔单已{action}", warnings

    # ---- 校验口径 -------------------------------------------------------

    def _normalize(
        self, values: dict[str, Any], *, submit: bool
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        """把表单值归一成落库值，并按正式提交口径返回阻断错误与非阻断提示。"""
        normalized: dict[str, Any] = {field: values.get(field) for field in FORM_FIELDS}
        errors: list[str] = []
        warnings: list[str] = []

        device_code = str(values.get("设备编号") or "").strip()
        asset = self._find_asset(device_code) if device_code else None
        if not device_code:
            if submit:
                errors.append("缺少设备编号")
        elif asset is None:
            errors.append(f"设备 {device_code} 不在资产台账里，无法核定赔付上限")
        else:
            normalized["设备编号"] = device_code
            normalized["设备类型"] = asset.get("设备类型")
            normalized["资产原值"] = _to_amount(asset.get("资产原值"))

        policy_no = str(values.get("保单号") or "").strip()
        policy = self._find_policy(policy_no) if policy_no else None
        if submit and not policy_no:
            errors.append("缺少保单号")
        elif policy_no and policy is None:
            errors.append(f"保单 {policy_no} 不存在")
        elif policy is not None:
            normalized["保单号"] = policy_no
            if asset is not None and str(policy.get("设备编号")) != device_code:
                errors.append(f"保单 {policy_no} 承保设备不是 {device_code}")

        report_date = _to_date(values.get("报案日期"))
        if submit and report_date is None:
            errors.append("报案日期缺失或格式不是 YYYY-MM-DD")
        if policy is not None and report_date is not None:
            start = _to_date(policy.get("保险起期"))
            end = _to_date(policy.get("保险止期"))
            if start is not None and end is not None and not (start <= report_date <= end):
                errors.append(
                    f"报案日期 {report_date.isoformat()} 不在保险期 "
                    f"{policy.get('保险起期')} ~ {policy.get('保险止期')} 内"
                )

        payout = _to_amount(values.get("赔付金额"))
        if submit:
            if payout is None:
                errors.append("赔付金额缺失或不是数字")
            elif payout <= 0:
                errors.append("赔付金额必须大于 0")
        normalized["赔付金额"] = payout

        for text_field in ("理赔单号", "出险原因", "超限依据", "材料清单"):
            text_value = values.get(text_field)
            normalized[text_field] = str(text_value).strip() if text_value is not None else ""

        if submit:
            for label, field in (
                ("出险原因", "出险原因"),
                ("理赔材料清单", "材料清单"),
            ):
                if not normalized.get(field):
                    errors.append(f"缺少{label}，材料不全请先保存草稿")

        # 赔付标准上限校验：超限必须写明依据（草稿不阻断，提交才阻断）。
        standard_cap: float | None = None
        if asset is not None:
            ratio = self._ratio(asset.get("设备类型"))
            standard_cap = round((_to_amount(asset.get("资产原值")) or 0.0) * ratio, 2)
            if payout is not None and payout > standard_cap:
                if not normalized.get("超限依据"):
                    if submit:
                        errors.append(
                            f"赔付金额 {payout:.2f} 超过赔付标准上限 {standard_cap:.2f}，"
                            "必须写明超限依据后才能保存"
                        )
                    warnings.append(
                        f"赔付金额 {payout:.2f} 超过赔付标准上限 {standard_cap:.2f}，提交前须补超限依据"
                    )

        # 保单口径：超单案赔付限额只提示、不拦截，提示随保存结果一起返回。
        if policy is not None and payout is not None:
            policy_cap = _to_amount(policy.get("单案赔付限额"))
            if policy_cap is not None and payout > policy_cap:
                warnings.append(
                    f"赔付金额 {payout:.2f} 高于保单单案赔付限额 {policy_cap:.2f}，与保单口径不一致，请复核"
                )
        return normalized, errors, warnings

    # ---- 重复报案判定 ---------------------------------------------------

    def _is_duplicate(self, row: dict[str, Any]) -> bool:
        if row.get("status") not in DUPLICATE_CANDIDATE_STATUSES:
            return False
        return bool(row.get("_duplicate"))

    def _first_recognized(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """返回同设备同保单期内最早的那条有效报案（被认的第一条）。"""
        device_code = row.get("设备编号")
        policy_no = row.get("保单号")
        candidates = [
            other for other in store.rows(MODULE)
            if other.get("status") in DUPLICATE_CANDIDATE_STATUSES
            and other.get("设备编号") == device_code
            and other.get("保单号") == policy_no
        ]
        if not candidates:
            return None

        def sort_key(item: dict[str, Any]) -> tuple[date, int]:
            parsed = _to_date(item.get("报案日期"))
            return parsed or date.max, int(item.get("id", 0))

        return min(candidates, key=sort_key)

    def _mark_duplicate_flags(self) -> None:
        """按 (设备编号, 保单号) 分组重算疑似重复标记。

        只在同一保单（同一保险期）内比较，所以跨期报案天然分组不同、可以并存；
        金额从不汇总，避免跨期金额被合并。
        """
        rows = store.rows(MODULE)
        for row in rows:
            row["_recognized"] = False
            row["_duplicate"] = False
        groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
        for row in rows:
            if row.get("status") not in DUPLICATE_CANDIDATE_STATUSES:
                continue
            groups.setdefault((row.get("设备编号"), row.get("保单号")), []).append(row)
        for members in groups.values():
            first = self._first_recognized(members[0])
            for row in members:
                if first is not None and int(row.get("id", 0)) == int(first.get("id", 0)):
                    row["_recognized"] = True
                else:
                    row["_duplicate"] = True
