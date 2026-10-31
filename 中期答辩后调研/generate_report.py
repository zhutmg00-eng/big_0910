#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调研报告生成脚本（research-report skill Step 3）。

读取 results/ 下全部 item JSON 与 fields.yaml，覆盖每个字段生成 report.md：
- 目录：序号 + 名称锚点 + 摘要字段（可配置）
- 正文：按 fields.yaml 的分类组织字段；跳过 [不确定] 值与 uncertain 数组列出的字段
- 额外字段（fields.yaml 未定义的 JSON 键）收入「其他信息」；过滤内部键

用法：.venv/Scripts/python.exe 中期答辩后调研/generate_report.py
（在仓库根目录执行；脚本内部按自身位置定位目录，与 cwd 无关）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
FIELDS_PATH = BASE / "fields.yaml"
OUT_PATH = BASE / "report.md"

# 目录摘要字段（用户可在重跑时修改此列表；须为 fields.yaml 中已定义的字段名）
SUMMARY_FIELDS = ["category", "doc_number", "publish_date"]

# JSON 中的内部键，不计入「其他信息」（name/category 保留在 flat 中供目录与排序使用）
_INTERNAL_KEYS = {"_source_file", "uncertain"}
# 分组容器键（若某 JSON 采用嵌套结构，这些键下的字段展开后按 fields.yaml 归组）
_CONTAINER_HINTS = {"基本信息", "核心内容", "对本项目的价值", "来源与可信度",
                    "basic_info", "technical_features", "performance_metrics"}


def load_fields() -> tuple[dict[str, list[dict]], list[str]]:
    """返回 (分类→字段定义列表, 全部字段名顺序列表)。"""
    data = yaml.safe_load(FIELDS_PATH.read_text(encoding="utf-8"))
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for cname, flist in (data.get("fields") or {}).items():
        if cname in _INTERNAL_KEYS:
            continue
        groups[cname] = [f for f in flist if isinstance(f, dict) and "name" in f]
        order.extend(f["name"] for f in groups[cname])
    return groups, order


def flatten_item(raw: dict) -> tuple[dict, list[str]]:
    """兼容两种结构：扁平（19字段在顶层）与嵌套（字段在分类容器下）。

    返回 (扁平化后的kv, 该item的uncertain字段名列表)。
    """
    flat: dict = {}
    for key, val in raw.items():
        if key in _INTERNAL_KEYS:
            continue
        if key in _CONTAINER_HINTS and isinstance(val, dict):
            flat.update(val)
        elif isinstance(val, dict) and key not in _CONTAINER_HINTS:
            # 未知嵌套 dict：整体保留，后面进「其他信息」
            flat[key] = val
        else:
            flat[key] = val
    return flat, list(raw.get("uncertain") or [])


def is_uncertain(field_name: str, value, uncertain_list: list[str]) -> bool:
    if field_name in uncertain_list:
        return True
    if value is None:
        return True
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return "[不确定]" in text


def fmt_value(value) -> str:
    """复杂值格式化：list[dict] 逐行 kv；普通 list 短逗号长换行；dict 递归；长文本加 <br>。"""
    if isinstance(value, list):
        if value and all(isinstance(x, dict) for x in value):
            lines = []
            for item in value:
                kv = " | ".join(f"**{k}**: {fmt_value(v)}" for k, v in item.items())
                lines.append(f"- {kv}")
            return "\n".join(lines)
        text = "、".join(str(x) for x in value)
        return text if len(text) <= 100 else text.replace("、", "、<br>")
    if isinstance(value, dict):
        kv = "；".join(f"{k}: {fmt_value(v)}" for k, v in value.items())
        return kv if len(kv) <= 100 else kv.replace("；", "；<br>")
    text = str(value)
    if len(text) > 100 and "<br>" not in text and "\n" not in text:
        text = text.replace("。", "。<br>")
    return text


def slug_anchor(text: str) -> str:
    """GitHub 风格锚点：去标点、空格转连字符、保留中文并小写。"""
    text = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", text)
    return re.sub(r"\s+", "-", text.strip()).lower()


def render_table_row(label: str, value: str) -> str:
    value = value or "—"
    if "\n" in value:
        return f"**{label}**：\n\n{value}\n"
    return f"**{label}**：{value}\n\n"


def main() -> int:
    groups, field_order = load_fields()
    jsons = sorted(RESULTS.glob("*.json"))
    if not jsons:
        print(f"[错误] {RESULTS} 下没有 JSON 结果文件", file=sys.stderr)
        return 1

    items = []
    for path in jsons:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[跳过] {path.name}: {exc}", file=sys.stderr)
            continue
        flat, uncertain = flatten_item(raw)
        items.append({"file": path.name, "flat": flat, "uncertain": uncertain})

    cat_of = lambda it: str(it["flat"].get("category") or "未分类")
    order = {"A类-意义侧": 0, "B类-准确性侧": 1}
    items.sort(key=lambda it: (order.get(cat_of(it), 9), it["file"]))

    lines: list[str] = []
    lines.append("# 物流碳决策助手 · 实际意义与数据准确性深度调研报告\n")
    lines.append(f"> 生成时间：{__import__('datetime').date.today().isoformat()} ｜ items：{len(items)} ｜ 来源：results/ 下 {len(jsons)} 个 JSON（fields.yaml 19 字段）\n")

    # ---- 目录 ----
    lines.append("## 目录\n")
    for i, it in enumerate(items, 1):
        name = str(it["flat"].get("name") or it["file"].removesuffix(".json"))
        heading = f"{i}. {name}"
        summary = " ｜ ".join(
            f"{f}: {it['flat'].get(f, '—')}" for f in SUMMARY_FIELDS
        )
        lines.append(f"{i}. [{name}](#{slug_anchor(heading)}) - {summary}")
    lines.append("")

    # ---- 正文：按 items 逐个展开 ----
    extra_bucket: dict[str, list[tuple[str, object]]] = {}
    skipped_uncertain = 0
    for i, it in enumerate(items, 1):
        name = str(it["flat"].get("name") or it["file"].removesuffix(".json"))
        lines.append(f"## {i}. {name}\n")
        known = set(field_order) | {"name", "category"}
        for gname, gfields in groups.items():
            lines.append(f"### {gname}\n")
            for fdef in gfields:
                fname = fdef["name"]
                if fname in it["uncertain"]:
                    skipped_uncertain += 1
                    lines.append(f"**{fname}**：_[不确定]_\n\n")
                    continue
                value = it["flat"].get(fname)
                if is_uncertain(fname, value, it["uncertain"]):
                    skipped_uncertain += 1
                    lines.append(f"**{fname}**：_[不确定]_\n\n")
                    continue
                lines.append(render_table_row(fname, fmt_value(value)))
        extras = [k for k in it["flat"] if k not in known]
        if extras:
            lines.append("### 其他信息\n")
            for k in extras:
                if k in _CONTAINER_HINTS:
                    continue
                lines.append(render_table_row(k, fmt_value(it["flat"][k])))
                extra_bucket.setdefault(k, []).append((name, it["flat"][k]))
        unc = it["uncertain"]
        if unc:
            lines.append("### 不确定字段\n")
            for u in unc:
                lines.append(f"- {u}\n")
        lines.append("---\n")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[完成] {OUT_PATH}")
    print(f"  items: {len(items)} ｜ [不确定]跳过字段次: {skipped_uncertain}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
