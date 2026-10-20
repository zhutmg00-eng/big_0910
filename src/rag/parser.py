"""政策文档解析器

支持格式：PDF, DOCX, HTML, Markdown, TXT
功能：解析 → 清洗 → 切分chunk
"""
from typing import List, Dict
from pathlib import Path
try:
    import pymupdf as fitz
except ImportError:  # 兼容旧版 PyMuPDF
    import fitz
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
from bs4 import BeautifulSoup
import re


_NOISE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ICP备",
        r"公网安备",
        r"网站标识码",
        r"版权所有",
        r"主办单位",
        r"运行维护单位",
        r"联系我们",
        r"中文域名",
        r"政务微(?:信|博)",
        r"扫一扫.*(?:手机|当前页|页面)",
        r"返回顶部",
        r"关闭窗口",
        r"网站地图",
        r"无障碍浏览",
        r"^(?:URL|网址)\s*:",
    )
]

_NAVIGATION_LINE = re.compile(
    r"^(?:首页|新闻|政策|公开|服务|互动|专题|手机版|微博|微信|中国政府网)$"
)


_CJK = r"\u3400-\u9fff\uf900-\ufaff"
_CJK_PUNCT = "，、；：（）《》“”‘’—…"
_SENTENCE_END = "。！？；：”）》"
_PUA_OR_BAD = re.compile(r"[\ue000-\uf8ff\ufffd\u25a1\u22a0\uf06c]")
_CJK_GAP = re.compile(rf"(?<=[{_CJK}{_CJK_PUNCT}])[ \t\u3000]+(?=[{_CJK}{_CJK_PUNCT}])")
_HEADING_START = re.compile(r"^(?:第[一二三四五六七八九十百零\d]+[章节条款部分]|[一二三四五六七八九十]+、|（[一二三四五六七八九十\d]+）|\d+[.、．])")


def join_cjk_wrapped_lines(text: str) -> str:
    """修复 PDF 版式换行：把中文句子中间被硬换行/空格拆开的地方重新拼接。

    PDF 抽取会在每个排版行末插入换行，后续再被替换为空格时就会出现
    “规 模化”“制修 订”这种断词，既影响 BM25 分词，也影响演示观感。
    规则：上一行不以句末标点结尾、下一行不是新条款编号时，两行直接相连。
    """
    text = _PUA_OR_BAD.sub("", text)
    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if (
            out and out[-1]
            and re.search(rf"[{_CJK}{_CJK_PUNCT}A-Za-z0-9]$", out[-1])
            and out[-1][-1] not in _SENTENCE_END
            and re.match(rf"[{_CJK}{_CJK_PUNCT}]", line)
            and not _HEADING_START.match(line)
        ):
            out[-1] += line
        else:
            out.append(line)
    return _CJK_GAP.sub("", "\n".join(out))


def parse_pdf(file_path: Path) -> str:
    """解析PDF文档为纯文本（含中文断行修复）"""
    with fitz.open(file_path) as doc:
        text_parts = [page.get_text() for page in doc]
    return join_cjk_wrapped_lines("\n".join(text_parts))


def parse_docx(file_path: Path) -> str:
    """解析Word文档为纯文本"""
    if not DOCX_AVAILABLE:
        print(f"[WARN] python-docx未安装，无法解析: {file_path.name}")
        return ""
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])


def parse_html(file_path: Path) -> str:
    """解析HTML文档为纯文本"""
    soup = BeautifulSoup(file_path.read_text(encoding="utf-8"), "html.parser")
    # 移除script和style标签
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def parse_document(file_path: Path) -> str:
    """根据文件扩展名自动选择解析器"""
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return parse_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return parse_docx(file_path)
    elif ext in (".html", ".htm"):
        return parse_html(file_path)
    elif ext in (".md", ".markdown", ".txt"):
        return file_path.read_text(encoding="utf-8")
    else:
        print(f"[WARN] 不支持的文件格式: {ext} ({file_path.name})")
        return ""


def clean_policy_text(raw_text: str) -> str:
    """
    清洗政策文档文本
    - 移除网页导航、备案号、版权页脚等抓取噪声
    - 去除 Markdown 标记并保留可读的标题和链接文字
    - 删除抓取页面中重复出现的长行
    """
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    lines = normalized.split("\n")
    cleaned = []
    seen_long_lines = set()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if _NAVIGATION_LINE.fullmatch(line) or any(pattern.search(line) for pattern in _NOISE_PATTERNS):
            continue
        if re.fullmatch(r"[-=_*#\s]{3,}", line):
            continue

        # Markdown 图片没有检索价值；普通链接保留可读文字。
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = line.replace("**", "").replace("__", "").replace("`", "").strip()
        if (
            not line
            or re.fullmatch(r"https?://\S+", line)
            or any(pattern.search(line) for pattern in _NOISE_PATTERNS)
        ):
            continue

        # 抓取结果经常把同一正文重复两遍；长行精确去重不会破坏章节标题。
        if len(line) >= 24:
            if line in seen_long_lines:
                continue
            seen_long_lines.add(line)
        cleaned.append(line)
    return "\n".join(cleaned)


def chunk_policy_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 150,
    doc_source: str = "",
    doc_date: str = "",
) -> List[Dict]:
    """
    将政策文档切分为可检索的chunk

    策略：
    - 以自然段落分割
    - 每个chunk约800字符（中文约400字），overlap 150字符
    - 每个chunk保留元数据

    Args:
        text: 清洗后的政策全文
        chunk_size: 每个chunk的最大字符数
        overlap: 相邻chunk的重叠字符数
        doc_source: 来源文档名
        doc_date: 文档发布日期

    Returns:
        List[Dict]: [{"text": "...", "metadata": {...}}, ...]
    """
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # 单个段落超过 chunk_size 时进行分片切分
        if len(para) > chunk_size:
            if current_chunk:
                chunks.append({
                    "text": current_chunk.strip(),
                    "metadata": {
                        "source": doc_source,
                        "date": doc_date,
                    },
                })
                current_chunk = ""
            start = 0
            while start < len(para):
                end = start + chunk_size
                slice_text = para[start:end]
                chunks.append({
                    "text": slice_text.strip(),
                    "metadata": {
                        "source": doc_source,
                        "date": doc_date,
                    },
                })
                if end >= len(para):
                    break
                start += max(1, chunk_size - overlap)
            continue

        if len(current_chunk) + len(para) > chunk_size:
            if current_chunk:
                chunks.append({
                    "text": current_chunk.strip(),
                    "metadata": {
                        "source": doc_source,
                        "date": doc_date,
                    },
                })
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                current_chunk = overlap_text + "\n" + para
            else:
                current_chunk = para
        else:
            current_chunk += "\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append({
            "text": current_chunk.strip(),
            "metadata": {
                "source": doc_source,
                "date": doc_date,
            },
        })

    return chunks


def process_document(file_path: Path, doc_date: str = "") -> List[Dict]:
    """
    完整处理流程：解析 → 清洗 → 切分

    Args:
        file_path: 文档文件路径
        doc_date: 文档发布日期

    Returns:
        List[Dict]: chunk列表
    """
    raw_text = parse_document(file_path)
    if not raw_text.strip():
        return []

    cleaned_text = clean_policy_text(raw_text)
    chunks = chunk_policy_text(
        cleaned_text,
        doc_source=file_path.name,
        doc_date=doc_date,
    )
    print(f"[DOC] {file_path.name}: {len(chunks)} 个chunk")
    return chunks
