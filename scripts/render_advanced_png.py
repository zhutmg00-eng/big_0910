"""使用 Playwright 将新生成的 SVG 图表渲染并截图为高清 PNG 格式，方便 PPT 直接引用与展示。"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACTS_DIR = Path(__file__).parent.parent / "docs" / "artifacts"

async def convert_svg_to_png(svg_name: str, png_name: str):
    svg_path = ARTIFACTS_DIR / svg_name
    png_path = ARTIFACTS_DIR / png_name
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{
          margin: 0;
          padding: 0;
          background: #0f172a;
          display: flex;
          justify-content: center;
          align-items: center;
          width: 1000px;
          height: 620px;
          overflow: hidden;
        }}
        img {{
          width: 1000px;
          height: 620px;
          display: block;
        }}
      </style>
    </head>
    <body>
      <img src="{svg_path.as_uri()}" />
    </body>
    </html>
    """
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1000, "height": 620}, device_scale_factor=2)
        await page.set_content(html_content)
        await asyncio.sleep(0.5)
        await page.screenshot(path=str(png_path))
        await browser.close()
        print(f"Rendered: {png_path}")

async def main():
    await convert_svg_to_png("fig4_baas_tco_comparison.svg", "fig4_baas_tco_comparison.png")
    await convert_svg_to_png("fig5_grid_scope2_green_power.svg", "fig5_grid_scope2_green_power.png")

if __name__ == "__main__":
    asyncio.run(main())
