"""车队台账导入：把企业手里的 CSV/Excel 车队清单解析成 ``VehicleInput`` 列表。

设计背景（第八轮独立评审的核心结论）：

> 最致命的短板不是算得不准，而是「根本没有把一家真实车队的账搬进去的入口」。
> 货运老板手里的是 Excel 台账（车型、数量、年里程、实载率），系统只给逐条
> 手填四个框的菜单，170 辆车要点 170 次，错一个数只能删行重来。

因此这里只做一件事：**容错地把任意列名/任意脏数据变成规范的车型分组**，
并且把每一处纠正都写进 ``warnings`` 让用户自己核对，绝不静默猜测。

三条硬约束：

1. 格式兼容性。原生支持 ``.csv``, ``.txt``（制表符/分号等）以及 ``.xlsx``
   格式（基于 openpyxl）。遇到旧版二进制 ``.xls``（Excel 97-2003）或损坏文件时，
   给出明确的另存为指引，避免直接崩溃。
2. 不静默丢数据。认不出的车型、为 0 或负数的车辆数、缺失的里程都会变成
   ``ImportWarning`` 级别的提示，用户在预览表上逐条改。
3. 同车型多行自动合并（合计车辆数、按车辆数加权平均里程与实载率），
   因为真实台账往往是「按车牌一行」的。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from src.engine.emission_factors import get_all_factors

# ----------------------------------------------------------------------------
# 列名容错映射
# ----------------------------------------------------------------------------
#: 目标字段 → 可能出现在台账表头里的写法（全部小写、去掉空白与括号后比较）。
_COLUMN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "vehicle_type": (
        "车型", "车辆类型", "车型名称", "车类", "类别", "类型", "车辆种类",
        "vehicletype", "vehicle_type", "type", "trucktype",
    ),
    "count": (
        "数量", "辆数", "车辆数", "台数", "车数", "保有量", "车辆数量", "台",
        "count", "quantity", "qty", "number", "num", "vehicles",
    ),
    "annual_km": (
        "年均里程", "年行驶里程", "年里程", "年度里程", "年均行驶里程",
        "单车年里程", "里程", "年行驶公里数", "年公里数", "年行驶里程km",
        "annualkm", "annual_km", "kmperyear", "km", "mileage",
    ),
    "load_factor": (
        "满载率", "实载率", "里程利用率", "装载率", "载重利用率",
        "loadfactor", "load_factor", "lf", "load",
    ),
}

#: 车型近义词。台账里的口语叫法 → 因子表里的规范车型。
#: 只放「一对一、无歧义」的映射；带吨位/燃料细分的一律交给下面的模糊匹配，
#: 避免把「重型自卸货车」错配成「重型柴油货车(>31t)」这类细分型号。
_VEHICLE_SYNONYMS: Dict[str, str] = {
    "重卡": "重型柴油货车",
    "重型卡车": "重型柴油货车",
    "重型牵引车": "重型柴油半挂牵引车(>49t)",
    "牵引车": "重型柴油半挂牵引车(>49t)",
    "半挂牵引车": "重型柴油半挂牵引车(>49t)",
    "中卡": "中型柴油货车",
    "中型卡车": "中型柴油货车",
    "轻卡": "轻型柴油货车",
    "轻型卡车": "轻型柴油货车",
    "微卡": "微型汽油货车",
    "微型卡车": "微型汽油货车",
    "面包车": "微型汽油货车",
    "新能源车": "新能源物流车",
    "电动车": "新能源物流车",
    "纯电动车": "新能源物流车",
    "纯电重卡": "新能源物流车",
    "电动重卡": "新能源物流车",
    "新能源重卡": "新能源物流车",
    "重型纯电动货车": "新能源物流车",
    "纯电动重卡": "新能源物流车",
    "重型纯电货车": "新能源物流车",
    "轻型纯电动货车": "新能源物流车",
    "轻型电动货车": "新能源物流车",
    "纯电轻卡": "新能源物流车",
    "电动轻卡": "新能源物流车",
    "纯电轻型卡车": "新能源物流车",
    "中型纯电动货车": "新能源物流车",
    "纯电中卡": "新能源物流车",
    "电动中卡": "新能源物流车",
    "纯电物流车": "新能源物流车",
    "电动物流车": "新能源物流车",
    "lng重卡": "LNG重型货车",
    "lng牵引车": "LNG重型货车",
    "液化天然气货车": "LNG重型货车",
}

#: 车数上限与里程上限。重卡年均里程物理上限约 25~30 万 km，
#: 超过它几乎一定是「单位填成了米」或「把月里程当成了年里程」。
MAX_UNITS_PER_ROW = 50_000
MAX_ANNUAL_KM = 300_000.0
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2_000

_NORMALISE_RE = re.compile(r"[\s\-_·・（）()\[\]{}#*:：/\\×x]+")


class FleetImportError(ValueError):
    """台账无法解析（缺列、空表、格式不支持等）。"""


@dataclass
class ImportWarning:
    """一条需要用户确认的纠正记录。"""

    row: int
    field_name: str
    message: str

    def as_dict(self) -> Dict[str, object]:
        return {"row": self.row, "field": self.field_name, "message": self.message}


@dataclass
class ImportedGroup:
    """合并后的车型分组。"""

    vehicle_type: str
    count: int
    annual_km: float
    load_factor: float
    rows: int = 1

    def as_dict(self) -> Dict[str, object]:
        return {
            "vehicle_type": self.vehicle_type,
            "count": self.count,
            "annual_km": round(self.annual_km, 2),
            "load_factor": round(self.load_factor, 4),
            "rows": self.rows,
        }


@dataclass
class FleetImportResult:
    groups: List[ImportedGroup] = field(default_factory=list)
    warnings: List[ImportWarning] = field(default_factory=list)
    total_vehicles: int = 0
    rows_read: int = 0
    detected_columns: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "groups": [g.as_dict() for g in self.groups],
            "warnings": [w.as_dict() for w in self.warnings],
            "total_vehicles": self.total_vehicles,
            "rows_read": self.rows_read,
            "detected_columns": self.detected_columns,
            "notes": self.notes,
        }


# ----------------------------------------------------------------------------
# 表头与取值
# ----------------------------------------------------------------------------
def _normalise_header(name: str) -> str:
    return _NORMALISE_RE.sub("", (name or "").strip().lower())


def _detect_columns(headers: Iterable[str]) -> Dict[str, str]:
    """把台账表头映射到目标字段。

    返回 ``{目标字段: 实际表头}``。同一目标字段匹配到多列时取第一列，
    并在 ``notes`` 里提示（由调用方写入），不抛异常——真实台账里
    「里程」和「年里程」同时出现很常见。
    """
    normalised = [(h, _normalise_header(h)) for h in headers if (h or "").strip()]
    detected: Dict[str, str] = {}
    for target, aliases in _COLUMN_ALIASES.items():
        for original, norm in normalised:
            if norm in aliases:
                detected.setdefault(target, original)
                break
    # 第二轮：允许「包含」匹配（如「年行驶里程(km)」规范化后是「年行驶里程km」）
    for target, aliases in _COLUMN_ALIASES.items():
        if target in detected:
            continue
        for original, norm in normalised:
            if any(alias in norm or norm in alias for alias in aliases if len(alias) >= 3):
                detected[target] = original
                break
    return detected


def _parse_number(raw: object, *, is_int: bool) -> Optional[float]:
    """把「1,200」「1 200」「1200km」「80,000 km/年」「75%」「4万公里」「8千」解析成数字。"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    text = str(raw).strip()
    if not text:
        return None
    percent = text.endswith("%")
    text = text.replace("%", "").replace(",", "").replace("，", "").replace(" ", "")
    text = re.sub(r"(km/年|公里/年|km|公里|辆|台|年|/年)", "", text, flags=re.IGNORECASE)
    text = text.strip()
    multiplier = 1.0
    if text.endswith(("万", "w", "W")):
        multiplier = 10000.0
        text = text[:-1].strip()
    elif text.endswith(("千", "k", "K")):
        multiplier = 1000.0
        text = text[:-1].strip()
    if not text or not re.fullmatch(r"[-+]?\d*\.?\d+", text):
        return None
    value = float(text) * multiplier
    if percent:
        value = value / 100.0
    return value if value == value else None


def resolve_vehicle_type(raw: str) -> Optional[str]:
    """把台账里的车型写法解析成因子表中的规范车型名。

    解析顺序：完全一致 → 近义词表 → 去括号后一致 → 最长子串包含。
    全部失败返回 ``None``（由调用方转成警告，不猜测）。
    """
    text = (raw or "").strip()
    if not text:
        return None
    known = list(get_all_factors().keys())
    if text in known:
        return text
    lowered = text.lower()
    if lowered in _VEHICLE_SYNONYMS:
        return _VEHICLE_SYNONYMS[lowered]
    bare = _NORMALISE_RE.sub("", lowered)
    for name in known:
        if _NORMALISE_RE.sub("", name.lower()) == bare:
            return name
    # 形如「重型柴油货车（>31t）」：去掉括号内容后再比一次
    stripped = re.sub(r"[（(][^）)]*[）)]", "", text).strip()
    if stripped in known:
        return stripped
    for name in known:
        name_stripped = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
        if name_stripped == stripped:
            return name
    # 去掉驱动型式这类与车型无关的修饰后再比一次：
    # 台账里大量出现「重型柴油 6×4 货车」「轻卡（4×2）」。
    simplified = re.sub(r"\d+\s*[×xX*]\s*\d+", " ", text)
    simplified = re.sub(r"\s{2,}", " ", simplified).strip()
    if simplified != text:
        return resolve_vehicle_type(simplified) if simplified else None
    # 最长子串：台账写「重型柴油货车 6×4」时应命中「重型柴油货车」
    candidates = [n for n in known if n and n in text]
    if candidates:
        return max(candidates, key=len)
    # 反向：台账写「重型柴油」而因子表是「重型柴油货车」
    reverse = [n for n in known if bare and bare in _NORMALISE_RE.sub("", n.lower())]
    if reverse:
        return min(reverse, key=len)
    return None


# ----------------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------------
def _decode_bytes(data: bytes) -> str:
    """CSV 常见编码依次尝试：UTF-8(BOM) → GBK → UTF-8 容错。

    国内台账大量是 Excel 另存的 GBK CSV，直接按 UTF-8 读会整表乱码。
    """
    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_rows(content: str) -> List[Dict[str, str]]:
    # 自动嗅探分隔符：Excel 中文环境常把逗号 CSV 存成分号/制表符分隔
    sample = content[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        for candidate in (",", ";", "\t", "|"):
            if candidate in sample:
                delimiter = candidate
                break
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        raise FleetImportError(
            "文件没有表头行，无法识别列。可以下载模板（GET /api/fleet/template，"
            "或在界面里点「下载 CSV 模板」）照着填。"
        )
    return [row for row in reader]


def parse_fleet_table(
    content: str,
    *,
    default_annual_km: Optional[float] = 80_000.0,
    default_load_factor: float = 0.75,
) -> FleetImportResult:
    """解析 CSV 文本为车型分组。

    Args:
        content: CSV 全文（已解码）。
        default_annual_km: 台账缺里程列或该格为空时的兜底值；``None`` 表示
            不允许缺失（缺失即视为错误行，不进入结果）。
        default_load_factor: 实载率缺省值。
    """
    result = FleetImportResult()
    rows = _read_rows(content)
    if len(rows) > MAX_ROWS:
        raise FleetImportError(
            f"行数 {len(rows)} 超过上限 {MAX_ROWS}。请先在 Excel 里按车型汇总成「车型+数量」再导入，"
            "逐车牌一行不需要导进来。"
        )
    if not rows:
        raise FleetImportError("文件里只有表头，没有数据行。")
    columns = _detect_columns(rows[0].keys())
    result.detected_columns = dict(columns)
    missing = [name for name in ("vehicle_type", "count") if name not in columns]
    if missing:
        cn = {"vehicle_type": "车型", "count": "数量"}
        raise FleetImportError(
            "缺少必需列：" + "、".join(cn[m] for m in missing)
            + "。已识别的列：" + ("、".join(columns.values()) or "无")
            + "。表头写法见下载模板（GET /api/fleet/template）。"
        )
    if "annual_km" not in columns:
        result.notes.append(
            f"未找到里程列，全部按默认 {default_annual_km or 0:,.0f} km/年 计算。"
            "里程是排放的最敏感参数，建议补齐。"
        )
    if "load_factor" not in columns:
        result.notes.append(f"未找到实载率列，全部按 {default_load_factor:.0%} 计算。")

    accum: Dict[str, Dict[str, float]] = {}
    for index, row in enumerate(rows, start=2):  # 2 = 表头占第 1 行
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue  # 空行（Excel 另存常见尾部空行）
        result.rows_read += 1

        raw_type = row.get(columns["vehicle_type"], "")
        resolved = resolve_vehicle_type(str(raw_type))
        if resolved is None:
            result.warnings.append(
                ImportWarning(index, "vehicle_type", f"第 {index} 行的车型「{str(raw_type).strip()}」无法识别，该行已跳过。")
            )
            continue

        count = _parse_number(row.get(columns["count"]), is_int=True)
        if count is None or count <= 0:
            result.warnings.append(
                ImportWarning(index, "count", f"第 {index} 行的数量「{row.get(columns['count'])}」不是正数，该行已跳过。")
            )
            continue
        if count > MAX_UNITS_PER_ROW:
            result.warnings.append(
                ImportWarning(index, "count", f"第 {index} 行的数量 {count:,.0f} 超过单行上限 {MAX_UNITS_PER_ROW:,}，已按上限处理。")
            )
            count = MAX_UNITS_PER_ROW
        if abs(count - round(count)) > 1e-9:
            result.warnings.append(
                ImportWarning(index, "count", f"第 {index} 行的数量 {count} 不是整数，已取整为 {round(count)}。")
            )
            count = round(count)

        raw_km = row.get(columns.get("annual_km", "")) if "annual_km" in columns else None
        km = _parse_number(raw_km, is_int=False) if "annual_km" in columns else None
        if km is None:
            if default_annual_km is None:
                result.warnings.append(
                    ImportWarning(index, "annual_km", f"第 {index} 行缺少里程且未设默认值，该行已跳过。")
                )
                continue
            km = float(default_annual_km)
            if "annual_km" in columns:
                raw_str = "" if raw_km is None else str(raw_km).strip()
                if raw_str:
                    result.warnings.append(
                        ImportWarning(index, "annual_km", f"第 {index} 行里程「{raw_str}」无法解析，按默认 {km:,.0f} km/年 计算。")
                    )
                else:
                    result.warnings.append(
                        ImportWarning(index, "annual_km", f"第 {index} 行里程为空，按默认 {km:,.0f} km/年 计算。")
                    )
        if km > MAX_ANNUAL_KM:
            result.warnings.append(
                ImportWarning(
                    index,
                    "annual_km",
                    f"第 {index} 行年均里程 {km:,.0f} km 超过重卡物理上限 {MAX_ANNUAL_KM:,.0f} km/年，"
                    "已按上限处理（请确认单位是 km 而不是 m，或是否把月里程填成了年里程）。",
                )
            )
            km = MAX_ANNUAL_KM

        lf = _parse_number(row.get(columns.get("load_factor", "")), is_int=False) if "load_factor" in columns else None
        if lf is None:
            lf = default_load_factor
        if lf > 1.0:
            # 「75」当成 75% 处理（台账里极常见），但 1.2 这种就钳到 1.0
            if lf <= 100.0:
                result.warnings.append(
                    ImportWarning(index, "load_factor", f"第 {index} 行实载率 {lf:g} 按百分数理解为 {lf / 100:.0%}。")
                )
                lf = lf / 100.0
            else:
                result.warnings.append(
                    ImportWarning(index, "load_factor", f"第 {index} 行实载率 {lf:g} 超出 0~1，已按 1.0 处理。")
                )
                lf = 1.0
        lf = min(max(lf, 0.0), 1.0)

        bucket = accum.setdefault(resolved, {"count": 0.0, "km_x_count": 0.0, "lf_x_count": 0.0, "rows": 0.0})
        bucket["count"] += float(count)
        bucket["km_x_count"] += float(count) * km
        bucket["lf_x_count"] += float(count) * lf
        bucket["rows"] += 1.0

    for vehicle_type, bucket in accum.items():
        total = int(round(bucket["count"]))
        if total <= 0:
            continue
        result.groups.append(
            ImportedGroup(
                vehicle_type=vehicle_type,
                count=total,
                annual_km=bucket["km_x_count"] / bucket["count"],
                load_factor=round(bucket["lf_x_count"] / bucket["count"], 4),
                rows=int(bucket["rows"]),
            )
        )
    result.total_vehicles = sum(g.count for g in result.groups)
    if not result.groups:
        raise FleetImportError(
            "没有任何一行被成功解析。请检查车型列是否为「" + "、".join(list(get_all_factors())[:4]) + "…」等规范车型名。"
        )
    merged = [g for g in result.groups if g.rows > 1]
    if merged:
        result.notes.append(
            "以下车型在文件中出现多行，已按车辆数加权合并："
            + "、".join(f"{g.vehicle_type}({g.rows} 行→{g.count} 辆)" for g in merged)
        )
    return result


def _excel_bytes_to_csv_text(data: bytes) -> str:
    """将 .xlsx 文件二进制内容转为标准 CSV 文本。"""
    try:
        import openpyxl
    except ImportError:
        raise FleetImportError(
            "当前运行环境未安装 openpyxl，无法直接解析 Excel 文件。"
            "请在 Excel 里「另存为 → CSV UTF-8（逗号分隔）」后再上传。"
        )
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = wb.active
        if sheet is None:
            raise FleetImportError("Excel 工作簿为空，未找到可用工作表。")
        output = io.StringIO()
        writer = csv.writer(output)
        has_content = False
        for row in sheet.iter_rows(values_only=True):
            if any(cell is not None and str(cell).strip() != "" for cell in row):
                has_content = True
                writer.writerow([str(c) if c is not None else "" for c in row])
        wb.close()
        if not has_content:
            raise FleetImportError("Excel 工作表内容为空，请检查后重试。")
        return output.getvalue()
    except FleetImportError:
        raise
    except Exception as exc:
        raise FleetImportError(
            f"读取 Excel 文件失败：{exc}。请检查文件是否损坏，或在 Excel 里「另存为 → CSV UTF-8（逗号分隔）」后重试。"
        )


def parse_fleet_file(
    filename: str,
    data: bytes,
    *,
    default_annual_km: Optional[float] = 80_000.0,
    default_load_factor: float = 0.75,
) -> FleetImportResult:
    """按扩展名分派：支持 .csv, .txt 以及 .xlsx 格式。"""
    if len(data) > MAX_CSV_BYTES:
        raise FleetImportError(f"文件 {len(data) / 1024:.0f} KB 超过 {MAX_CSV_BYTES // 1024} KB 上限。")
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        content = _excel_bytes_to_csv_text(data)
    elif name.endswith(".xls"):
        raise FleetImportError(
            "暂不支持旧版 .xls 格式（Excel 97-2003）。请在 Excel 里「另存为 → .xlsx」或「另存为 → CSV UTF-8」后再上传。"
        )
    elif name.endswith((".csv", ".txt", "")):
        content = _decode_bytes(data)
    else:
        raise FleetImportError(f"不支持的文件类型：{filename}。请上传 .xlsx 或 .csv 文件。")
    return parse_fleet_table(
        content,
        default_annual_km=default_annual_km,
        default_load_factor=default_load_factor,
    )
