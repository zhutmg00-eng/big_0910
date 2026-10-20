"""中文 BM25 稀疏检索。

使用 jieba 精确模式分词 + 领域词典 + 停用词过滤，Okapi BM25 (k1=1.5, b=0.75)。
与旧版“字符 n-gram 覆盖率 + 人工主题加权”的启发式打分相比，BM25 是信息
检索领域的标准基线，参数无需针对评测集调优，可复现、可解释。

jieba 不可用时自动降级为字符 2-gram 切分，保证系统可运行。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence

# 碳市场 / 交通领域专业术语：加入分词词典，避免被切碎
DOMAIN_TERMS = [
    "碳排放权", "碳排放", "碳交易", "碳市场", "全国碳市场", "碳达峰", "碳中和", "双碳",
    "配额", "配额分配", "配额清缴", "清缴", "履约", "重点排放单位", "排放因子",
    "温室气体", "自愿减排", "核证自愿减排量", "CCER", "方法学", "额外性",
    "核算", "核查", "监测计划", "MRV", "数据质量", "检验检测",
    "物流", "道路运输", "公路运输", "水路运输", "营业性", "货车", "重型货车",
    "柴油货车", "新能源", "新能源物流车", "纯电动", "氢燃料电池", "LNG",
    "满载率", "实载率", "周转量", "吨公里", "燃料消耗量", "燃料消耗量限值",
    "发电行业", "钢铁行业", "水泥", "铝冶炼", "基准值", "基准线", "碳价",
    "生态环境部", "交通运输部", "暂行条例", "管理办法", "征求意见稿", "试点",
]

STOPWORDS = set(
    "的 了 和 与 及 或 等 是 在 对 为 以 于 把 被 将 由 从 向 其 之 而 并 且 也 就 都 "
    "这 那 该 本 各 个 有 无 不 没 吗 呢 吧 啊 哪些 什么 怎么 如何 是否 多少 请 问 "
    "我们 你们 他们 公司 企业 咨询 一下 以及 关于 进行 相关 有关 规定 要求 应当 "
    "可以 需要 目前 当前 现在 如果 因为 所以 但是 还是 已经 一个 一些 这些 那些".split()
)

_jieba = None


def _get_jieba():
    global _jieba
    if _jieba is None:
        try:
            import jieba  # type: ignore

            jieba.setLogLevel(60)
            for term in DOMAIN_TERMS:
                jieba.add_word(term, freq=200000)
            _jieba = jieba
        except ImportError:  # pragma: no cover - 依赖缺失时降级
            _jieba = False
    return _jieba


_PUNCT = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def tokenize(text: str) -> List[str]:
    """中文分词（jieba 精确模式），过滤停用词与标点。"""
    text = text.lower()
    jb = _get_jieba()
    if jb:
        tokens = [t.strip() for t in jb.lcut(text)]
    else:
        compact = _PUNCT.sub("", text)
        tokens = [compact[i:i + 2] for i in range(max(len(compact) - 1, 0))]
    return [t for t in tokens if t and not _PUNCT.fullmatch(t) and t not in STOPWORDS]


class BM25Index:
    """内存 Okapi BM25 索引（政策库规模为数百~数千块，常驻内存即可）。"""

    def __init__(self, ids: Sequence[str], texts: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.ids = list(ids)
        self.k1, self.b = k1, b
        self.doc_tokens = [tokenize(t) for t in texts]
        self.doc_len = [len(toks) for toks in self.doc_tokens]
        self.avgdl = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.tf = [Counter(toks) for toks in self.doc_tokens]
        df: Counter = Counter()
        for toks in self.doc_tokens:
            df.update(set(toks))
        n = len(self.doc_tokens)
        # BM25+ 风格的非负 IDF
        self.idf: Dict[str, float] = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def __len__(self) -> int:
        return len(self.ids)

    def scores(self, query: str) -> List[float]:
        q_terms = tokenize(query)
        out = [0.0] * len(self.ids)
        if not q_terms or not self.ids:
            return out
        for i, tf in enumerate(self.tf):
            dl = self.doc_len[i] or 1
            norm = self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            s = 0.0
            for term in q_terms:
                f = tf.get(term)
                if f:
                    s += self.idf.get(term, 0.0) * f * (self.k1 + 1) / (f + norm)
            out[i] = s
        return out

    def top_k(self, query: str, k: int = 10) -> List[tuple[int, float]]:
        scored = [(i, s) for i, s in enumerate(self.scores(query)) if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60,
                           weights: Sequence[float] | None = None) -> List[tuple[str, float]]:
    """倒数排名融合 (Cormack et al., SIGIR 2009)：score(d) = Σ w_i / (k + rank_i(d))。

    RRF 只使用名次、不依赖各检索器分数的量纲，因此无需分数归一化，
    也无需在评测集上调融合权重，k=60 为原论文推荐值。
    """
    weights = list(weights) if weights else [1.0] * len(rankings)
    fused: Dict[str, float] = {}
    for w, ranking in zip(weights, rankings):
        for rank, doc_id in enumerate(ranking, 1):
            fused[doc_id] = fused.get(doc_id, 0.0) + w / (k + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)
