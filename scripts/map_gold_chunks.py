#!/usr/bin/env python3
"""40题基准数据集 Gold Chunk ID 精准映射与数据集生成脚本

根据 double-blind 独立审校标注结果（docs/rag_benchmark/review/标注表_标注者A.csv 及 40题题库），
将 40 道标准题的标准锚点定位与库内已固化的 268 个 Chunk 进行精准对齐与映射，
生成规范的 JSON / CSV 评测金标数据集。
"""
import sys
import re
import csv
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.vector_store import PolicyVectorStore

def load_questions_from_md(md_path: Path):
    """从 rag_benchmark_40_questions.md 解析 40 题完整结构"""
    content = md_path.read_text(encoding="utf-8")
    # 提取所有表格行 | Qxx | ...
    pattern = re.compile(r"^\|\s*(Q\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|", re.MULTILINE)
    questions = {}
    for match in pattern.finditer(content):
        qid, theme, qtype, diff, qtext, answer, sources, app_label, notes = [m.strip() for m in match.groups()]
        questions[qid] = {
            "id": qid,
            "theme": theme,
            "type": qtype,
            "difficulty": diff,
            "question": qtext,
            "answer": answer,
            "source_files": [s.strip() for s in sources.split("；") if s.strip()],
            "applicability_label": app_label,
            "notes": notes,
        }
    return questions

def load_gold_anchors(csv_path: Path):
    """从审校表中读取金标锚点定位"""
    anchors = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row.get("题号", "") or row.get("\ufeff题号", "")
            if not qid:
                for k, v in row.items():
                    if "题号" in k:
                        qid = v
                        break
            qid = qid.strip()
            anchor = row.get("[gold]锚点定位(文件-章节/关键词)", "").strip()
            anchors[qid] = anchor
    return anchors

def find_matching_chunk(chunks_for_file, keywords):
    """在文件对应的 chunks 中根据关键词定位最匹配的 chunk_id"""
    best_id = None
    best_score = -1
    for cid, idx, txt in chunks_for_file:
        match_count = sum(1 for kw in keywords if kw in txt)
        if match_count > best_score:
            best_score = match_count
            best_id = cid
    return best_id

def map_all_gold_chunks():
    vs = PolicyVectorStore()
    all_items = vs.collection.get(include=["documents", "metadatas"])
    docs = all_items["documents"]
    ids = all_items["ids"]
    metas = all_items["metadatas"]

    file_chunks = {}
    for i, cid in enumerate(ids):
        src = metas[i]["source"]
        idx = metas[i]["chunk_index"]
        txt = docs[i]
        if src not in file_chunks:
            file_chunks[src] = []
        file_chunks[src].append((cid, idx, txt))

    for src in file_chunks:
        file_chunks[src].sort(key=lambda x: x[1])

    q_md_path = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_40_questions.md"
    review_a_path = PROJECT_ROOT / "docs" / "rag_benchmark" / "review" / "标注表_标注者A.csv"

    questions = load_questions_from_md(q_md_path)
    anchors = load_gold_anchors(review_a_path)

    print(f"Loaded {len(questions)} questions from Markdown, {len(anchors)} anchors from Review CSV.")

    dataset = []
    for qid in sorted(questions.keys()):
        q = questions[qid]
        anchor = anchors.get(qid, "")
        q["gold_anchor"] = anchor

        matched_gold_chunks = []
        # 分解 anchor 中的文档及章节关键词
        anchor_parts = [p.strip() for p in anchor.split("；") if p.strip()]
        for part in anchor_parts:
            # 格式：文件名-章节/关键词 或 文件名
            if "-" in part:
                fname, kw_part = part.split("-", 1)
            else:
                fname, kw_part = part, ""
            fname = fname.strip()
            keywords = [k.strip() for k in re.split(r"[/、\s]+", kw_part) if k.strip()]

            if fname in file_chunks:
                cid = find_matching_chunk(file_chunks[fname], keywords)
                if cid and cid not in matched_gold_chunks:
                    matched_gold_chunks.append(cid)
            else:
                # 模糊匹配文件名
                for avail_file in file_chunks:
                    if fname in avail_file or avail_file in fname:
                        cid = find_matching_chunk(file_chunks[avail_file], keywords)
                        if cid and cid not in matched_gold_chunks:
                            matched_gold_chunks.append(cid)
                        break

        # 如果没有匹配到，使用首选来源文件的第一个 chunk 作为兜底候选
        if not matched_gold_chunks and q["source_files"]:
            primary_src = q["source_files"][0]
            if primary_src in file_chunks and file_chunks[primary_src]:
                matched_gold_chunks.append(file_chunks[primary_src][0][0])

        q["gold_chunk_ids"] = matched_gold_chunks
        dataset.append(q)

    # 导出为 JSON 和 CSV
    out_json = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json"
    out_json.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 金标评测集已成功导出至 JSON: {out_json}")

    out_csv = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.csv"
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["id", "theme", "type", "difficulty", "question", "answer", "applicability_label", "source_files", "gold_chunk_ids", "gold_anchor", "notes"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in dataset:
            row = dict(d)
            row["source_files"] = "；".join(row["source_files"])
            row["gold_chunk_ids"] = "；".join(row["gold_chunk_ids"])
            writer.writerow(row)
    print(f"✅ 金标评测集已成功导出至 CSV: {out_csv}")

    # 打印前 5 题示例
    print("\n--- 映射样本验证 (Top 5) ---")
    for d in dataset[:5]:
        print(f"[{d['id']}] {d['theme']} -> Gold Chunks: {d['gold_chunk_ids']}")

if __name__ == "__main__":
    map_all_gold_chunks()
