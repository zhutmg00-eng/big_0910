"""车队台账导入 API 与模板下载。

配合 ``src/engine/fleet_import.py``：前端上传 CSV → 后端解析成规范的车型分组
→ 用户在前端预览表里核对/修改 → 再点「计算排放基线」走原有 ``/api/calculate``。
这样导入不改变任何核算口径，只是替换掉「逐条手填」这个环节。
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from src.api.main import verify_api_key
from src.engine.emission_factors import get_all_factors
from src.engine.fleet_import import FleetImportError, parse_fleet_file

router = APIRouter(prefix="/api/fleet", tags=["车队台账导入"])

#: 模板列名。保持中文，与货运企业台账的习惯一致。
TEMPLATE_HEADERS = ["车型", "数量", "年均里程(km)", "实载率"]


def _template_rows() -> list[list[object]]:
    return [
        ["重型柴油货车", 40, 110000, 0.72],
        ["重型柴油半挂牵引车(>49t)", 25, 135000, 0.68],
        ["轻型柴油货车", 30, 45000, 0.60],
        ["LNG重型货车", 10, 120000, 0.75],
    ]


@router.get(
    "/template",
    response_class=PlainTextResponse,
    summary="下载车队台账 CSV 模板",
    description="返回带 BOM 的 UTF-8 CSV，Excel 双击不会乱码；含 4 行示例数据与列说明。",
)
def fleet_template() -> PlainTextResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerows(_template_rows())
    writer.writerow([])
    writer.writerow(["# 说明"])
    writer.writerow(["# 车型必须能从下列规范名称中识别（也可写常见的口语简称，如 重卡 / 轻卡 / LNG重卡 / 电动重卡）："])
    for name in get_all_factors():
        writer.writerow([f"#   {name}"])
    writer.writerow(["# 数量：该车型的车辆台数；可以按车牌一行一辆，系统会自动按车型合并"])
    writer.writerow(["# 年均里程：单台车一年的行驶公里数（km/年），不是月里程"])
    writer.writerow(["# 实载率：0~1 之间（1.0 = 满载）；填 75 会被理解为 75%"])
    # utf-8-sig：Excel 直接双击打开中文不乱码
    return PlainTextResponse(
        "\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="fleet_template.csv"'},
    )


@router.post(
    "/import",
    summary="解析车队台账 CSV（只解析，不计算）",
    description=(
        "上传 CSV 台账，返回规范化后的车型分组、需要用户确认的纠正记录（warnings）"
        "与识别到的列。前端应把 groups 回填到录入表让用户核对，再调用 /api/calculate。"
    ),
)
async def import_fleet(
    file: UploadFile = File(..., description="CSV 台账文件"),
    default_annual_km: float | None = Form(80_000, description="缺失里程时的兜底值，留空表示不允许缺失"),
    default_load_factor: float = Form(0.75, description="缺失实载率时的兜底值"),
    api_key: str = Depends(verify_api_key),
) -> dict:
    raw = await file.read()
    try:
        result = parse_fleet_file(
            file.filename or "",
            raw,
            default_annual_km=default_annual_km,
            default_load_factor=default_load_factor,
        )
    except FleetImportError as exc:
        # 400 而不是 422：这是「文件内容不符合模板」的业务错误，不是请求体校验失败
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = result.as_dict()
    payload["filename"] = file.filename
    payload["size_bytes"] = len(raw)
    return payload
