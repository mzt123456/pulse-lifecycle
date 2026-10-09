"""中文检索基线：jieba 分词 + 自研 BM25，支持结构化预过滤。

为什么不用向量库：当前语料规模只有几百到几千条，内存倒排索引的单次检索在
毫秒级，引入向量数据库与嵌入服务属于过度设计。语料上到十万级、或需要跨语言
与语义泛化时再换向量检索，检索层的入参与出参保持不变。
"""

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import jieba

from app.ai import lexicon
from app.ai.document import CaseDocument

# 行业术语在导入时注入 jieba，索引与查询共用同一套切分规则
lexicon.load_lexicon()

# 型号里带连字符（YST-48R、PLT-DEMO-1），必须整体保留，否则会被切成无意义的碎片
TOKEN_PATTERN = re.compile(r"[0-9a-zA-Z]+(?:-[0-9a-zA-Z]+)*|[\u4e00-\u9fff]+")

# 只保留高频虚词与无区分度的过程性词汇，避免把「现象」「问题」这类词当成检索信号。
# 「设备」「仪器」是语料渲染时的栏目标签（【设备型号】），出现在几乎每条文档里，
# 留着会让任意查询都命中一堆结果，所以按无区分度词处理。
STOPWORDS = frozenset(
    {
        "的", "了", "和", "与", "及", "或", "在", "是", "为", "有", "对", "被", "把",
        "上", "下", "前", "后", "时", "中", "内", "外", "出现", "发生", "问题", "情况",
        "现象", "异常", "进行", "导致", "造成", "无法", "不能",
        "设备", "仪器", "编号", "记录",
    }
)

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75

# 出现在超过一半文档里的词几乎没有区分度（DF 过滤），但语料很小的时候
# 会把本来有效的词也判成高频词，所以只在语料达到一定规模后启用。
DF_FILTER_MIN_DOCS = 10
DF_FILTER_RATIO = 0.5


def tokenize(text: str | None) -> list[str]:
    """中文按搜索模式切分，英文与数字整体保留，过滤停用词与单字。"""
    tokens: list[str] = []
    for chunk in TOKEN_PATTERN.findall(text or ""):
        if chunk.isascii():
            tokens.append(chunk.lower())
            continue
        for word in jieba.cut_for_search(chunk):
            word = word.strip()
            if len(word) < 2 or word in STOPWORDS:
                continue
            tokens.append(word)
    return tokens


@dataclass(frozen=True)
class SearchHit:
    """检索结果：命中的文档、得分与命中的查询词，便于解释「为什么召回它」。"""

    document: CaseDocument
    score: float
    matched_terms: tuple[str, ...]


class BM25Index:
    """基于内存倒排索引的 BM25，支持按 payload 字段做结构化预过滤。"""

    def __init__(
        self,
        documents: Sequence[CaseDocument],
        *,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
    ) -> None:
        self._documents = list(documents)
        self._k1 = k1
        self._b = b
        self._term_freqs = [Counter(tokenize(doc.text)) for doc in self._documents]
        self._lengths = [sum(tf.values()) for tf in self._term_freqs]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

        self._doc_freq: Counter[str] = Counter()
        for term_freq in self._term_freqs:
            self._doc_freq.update(term_freq.keys())

    def __len__(self) -> int:
        return len(self._documents)

    @property
    def documents(self) -> tuple[CaseDocument, ...]:
        return tuple(self._documents)

    def _idf(self, term: str) -> float:
        """带平滑的 IDF，取值恒为正，避免高频词得负分。"""
        freq = self._doc_freq.get(term, 0)
        return math.log(1 + (len(self._documents) - freq + 0.5) / (freq + 0.5))

    def _is_discriminative(self, term: str, max_doc_freq: float) -> bool:
        """词是否具备区分度：语料够大时，过滤掉出现在半数以上文档里的词。"""
        if len(self._documents) < DF_FILTER_MIN_DOCS:
            return True
        return self._doc_freq.get(term, 0) <= max_doc_freq

    def _candidates(self, filters: Mapping[str, object] | None) -> Iterable[int]:
        if not filters:
            return range(len(self._documents))
        return (
            index
            for index, doc in enumerate(self._documents)
            if all(doc.payload.get(key) == value for key, value in filters.items())
        )

    def search(
        self,
        query: str | None,
        *,
        top_k: int = 5,
        filters: Mapping[str, object] | None = None,
    ) -> list[SearchHit]:
        """检索最相关的文档；top_k 非正时返回空列表。"""
        if top_k <= 0:
            return []

        # 查询先做口语到规范表述的扩展，索引侧不动，保证两侧切分规则一致
        terms = tokenize(lexicon.expand_query(query))
        if not terms:
            return []

        max_doc_freq = DF_FILTER_RATIO * len(self._documents)
        unique_terms = sorted(
            term for term in set(terms) if self._is_discriminative(term, max_doc_freq)
        )
        if not unique_terms:
            # 查询里全是语料中的高频词：与其返回一堆弱相关结果，不如明说没找到
            return []
        idf = {term: self._idf(term) for term in unique_terms}

        hits: list[SearchHit] = []
        for index in self._candidates(filters):
            term_freq = self._term_freqs[index]
            length = self._lengths[index] or 1
            normalization = self._k1 * (1 - self._b + self._b * length / self._avg_length)

            score = 0.0
            matched: list[str] = []
            for term in unique_terms:
                freq = term_freq.get(term, 0)
                if not freq:
                    continue
                matched.append(term)
                score += idf[term] * (freq * (self._k1 + 1)) / (freq + normalization)

            if score > 0:
                hits.append(
                    SearchHit(
                        document=self._documents[index],
                        score=score,
                        matched_terms=tuple(matched),
                    )
                )

        # 得分相同时按 doc_id 兜底排序，保证结果稳定可复现
        hits.sort(key=lambda hit: (-hit.score, hit.document.doc_id))
        return hits[:top_k]


@dataclass(frozen=True)
class SearchOutcome:
    """检索结果与「是否放宽了结构化条件」的标记。"""

    hits: tuple[SearchHit, ...]
    relaxed: bool


def search_with_fallback(
    index: BM25Index,
    query: str | None,
    *,
    top_k: int = 5,
    filters: Mapping[str, object] | None = None,
) -> SearchOutcome:
    """先按结构化条件检索，条件过窄没有结果时放宽条件再试一次。

    故障类型、仪器类型是用户可选的过滤项，取值准确时能显著提高精度；
    但取值与语料标注口径不一致时（例如某台设备型号填的是自由文本），
    严格过滤会把唯一相关的案例挡在外面。这里宁可放宽并明确告知，
    也不要静默返回空结果。
    """
    hits = index.search(query, top_k=top_k, filters=filters)
    if hits or not filters:
        return SearchOutcome(hits=tuple(hits), relaxed=False)

    relaxed_hits = index.search(query, top_k=top_k)
    return SearchOutcome(hits=tuple(relaxed_hits), relaxed=bool(relaxed_hits))
