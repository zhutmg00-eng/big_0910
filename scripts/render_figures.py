#!/usr/bin/env python3
"""将 docs/artifacts/ 中的 SVG 转换为精准无多余空白的高清 PNG 图表"""
import re
from pathlib import Path
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:
    import pymupdf as fitz
except ImportError:
    import fitz

ARTIFACTS_DIR = Path(__file__).parent.parent / "docs" / "artifacts"

def convert_all():
    for svg_path in sorted(ARTIFACTS_DIR.glob("fig*.svg")):
        text = svg_path.read_text(encoding="utf-8")
        match = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
        if match:
            vw, vh = match.group(1), match.group(2)
            # 替换为精准尺寸，避免 Letter 纸张空白
            text = re.sub(r'width="[^"]*" height="[^"]*"', f'width="{vw}" height="{vh}"', text)
            svg_path.write_text(text, encoding="utf-8")

        doc = fitz.open(str(svg_path))
        page = doc[0]
        # 放大为高清 250 DPI
        pix = page.get_pixmap(dpi=250)
        png_path = svg_path.with_suffix(".png")
        pix.save(str(png_path))
        print(f"✅ 转换完成: {svg_path.name} -> {png_path.name} ({pix.width}x{pix.height})")

if __name__ == "__main__":
    convert_all()
