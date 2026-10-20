"""政策文档爬取

注意：实际使用时需遵守各网站robots协议和terms of service
建议优先手动从各官网"信息公开"栏目下载
"""
import requests
from pathlib import Path
from typing import List
import time

# 重点政策来源
POLICY_SOURCES = [
    {
        "name": "全国碳市场信息网",
        "base_url": "https://www.cets.org.cn",
        "pages": ["/tzgg/", "/zcfg/"],
    },
    {
        "name": "生态环境部",
        "base_url": "https://www.mee.gov.cn",
        "pages": ["/ywgz/ydqhbh/wsqtkz/"],
    },
    {
        "name": "北京绿色交易所",
        "base_url": "https://www.cbeex.com.cn",
        "pages": ["/article/zxdt/", "/article/flfg/"],
    },
    {
        "name": "上海环境能源交易所",
        "base_url": "https://www.cneeex.com.cn",
        "pages": ["/xxfw/zcfg/", "/xxfw/tzgg/"],
    },
    {
        "name": "广东碳排放交易所",
        "base_url": "https://www.cnemission.com",
        "pages": ["/article/zcfg/", "/article/tzgg/"],
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def download_file(url: str, output_path: Path, timeout: int = 30) -> bool:
    """下载单个文件"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"❌ 下载失败 {url}: {e}")
        return False


def download_policy_docs(urls: List[str], output_dir: Path) -> List[Path]:
    """
    批量下载政策文档

    Args:
        urls: 文档URL列表
        output_dir: 输出目录

    Returns:
        成功下载的文件路径列表
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for i, url in enumerate(urls):
        filename = url.split("/")[-1] or f"doc_{i}.pdf"
        if "." not in filename:
            filename = f"doc_{i}.pdf"
        output_path = output_dir / filename

        if download_file(url, output_path):
            downloaded.append(output_path)
            print(f"✅ 已下载 ({i+1}/{len(urls)}): {filename}")
        time.sleep(1)  # 礼貌延迟

    print(f"\n下载完成: {len(downloaded)}/{len(urls)} 个文件")
    return downloaded
