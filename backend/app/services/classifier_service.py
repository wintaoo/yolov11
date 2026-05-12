"""
统一图纸分类服务 - 多信号融合 + 置信度评分

信号源权重:
  figure_name   5.0x  (图名直接包含类别名)
  stage_pattern 5.0x  (X阶段施工平面布置图 → 对应阶段类别)
  context       1.0x  (文档段落上下文)
  filename      0.8x  (文件名，信号弱)

关键词分层:
  anchor (Tier1)   独有锚定词，几乎只在某一类出现 → 计 3 分
  supporting (Tier2) 辅助词，可能跨类但仍有区分力 → 计 1 分
  独有性加成: 仅出现在一个类别的锚定词额外 ×2
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 13个目标分类
ALL_CATEGORIES = [
    '总平面布置图', '基础结构图', '主体结构图', '土方工程图',
    '进度计划图', '施工计划图', '分区规划图', '施工分区图',
    '临时用电布置图', '临时用水布置图', '临建设施平面布置图',
    '装饰装修图', '周边环境图',
]

# 分层关键词表: anchor(3分) + supporting(1分)
# anchor = 高区分度锚定词，几乎不出现在其他类别
# supporting = 辅助辨别词，有区分力但可能跨类
CATEGORY_KEYWORDS: dict[str, dict[str, list[str]]] = {
    '周边环境图': {
        'anchor': [
            '周边环境', '项目区位', '现场踏勘', '周边地貌',
            '周边现状', '地理位置',
        ],
        'supporting': [
            '踏勘', '区位图', '环境图', '周边概况',
        ],
    },
    '进度计划图': {
        'anchor': [
            '进度计划', '横道图', '甘特图', '开竣工',
            '工期安排', '网络图',
        ],
        'supporting': [
            '施工进度', '进度图', '进度表',
        ],
    },
    '分区规划图': {
        'anchor': [
            '分区规划', '阶段划分', '分区示意',
        ],
        'supporting': [
            '规划图', '分区图',
        ],
    },
    '总平面布置图': {
        'anchor': [
            '总平面布置', '施工总平面', '总平布置',
        ],
        'supporting': [
            '平面布置图', '总平面', '总平图', '场地布置',
        ],
    },
    '基础结构图': {
        'anchor': [
            '基础结构', '桩基', '筏板', '承台',
            '桩位', '基础平面',
        ],
        'supporting': [
            '基础图', '基础施工', '结构布置',
        ],
    },
    '临时用电布置图': {
        'anchor': [
            '临时用电', '用电布置', '临电',
            '配电房', '配电箱',
        ],
        'supporting': [
            '配电', '用电图', '临电图', '现场用电',
        ],
    },
    '临时用水布置图': {
        'anchor': [
            '临时用水', '用水布置', '临水',
            '给水', '供水',
        ],
        'supporting': [
            '排水', '用水图', '临水图', '现场用水',
        ],
    },
    '土方工程图': {
        'anchor': [
            '土方工程', '土方开挖', '基坑',
            '土钉墙', '挖方',
        ],
        'supporting': [
            '土方图', '开挖图', '边坡', '支护',
        ],
    },
    '主体结构图': {
        'anchor': [
            '主体结构', '剪力墙', '柱网',
            '梁板', '结构平面',
        ],
        'supporting': [
            '主体图', '主体施工', '结构层',
            '结构施工', '框架',
        ],
    },
    '装饰装修图': {
        'anchor': [
            '装饰装修', '精装修', '园林绿化',
            '绿化种植', '景观施工', '硬质铺装',
        ],
        'supporting': [
            '装修图', '装饰图', '装修做法',
            '外立面', '内装', '绿化施工', '铺装',
        ],
    },
    '施工计划图': {
        'anchor': [
            '施工计划', '施工部署', '总体安排',
        ],
        'supporting': [
            '施工安排', '计划图', '施工组织',
        ],
    },
    '临建设施平面布置图': {
        'anchor': [
            '临建设施', '临建平面', '临建布置',
            '活动板房', '标养室',
        ],
        'supporting': [
            '临建图', '临设', '临时设施',
            '办公区', '生活区', '宿舍', '食堂',
            '门卫', '洗车', '办公室',
        ],
    },
    '施工分区图': {
        'anchor': [
            '施工分区', '施工段划分', '流水段',
        ],
        'supporting': [
            '分区施工', '施工段',
        ],
    },
}

# 计算每个关键词的"独有性"：只出现在一个类别的关键词
# {keyword: True} 表示该词仅在一个类别出现
_KEYWORD_UNIQUENESS: dict[str, bool] = {}

def _build_uniqueness():
    """预计算每个关键词的独有性（只出现在一个类别 = True）"""
    global _KEYWORD_UNIQUENESS
    if _KEYWORD_UNIQUENESS:
        return
    kw_cats: dict[str, set] = {}
    for cat, tiers in CATEGORY_KEYWORDS.items():
        for tier in ('anchor', 'supporting'):
            for kw in tiers[tier]:
                kw_cats.setdefault(kw, set()).add(cat)
    _KEYWORD_UNIQUENESS = {kw: len(cats) == 1 for kw, cats in kw_cats.items()}

_build_uniqueness()

# 信号权重
SIGNAL_WEIGHTS = {
    'figure_name': 5.0,
    'stage_pattern': 5.0,
    'context': 1.0,
    'filename': 0.8,
}

# 分层计分: anchor=3, supporting=1, 独有词额外 ×2
ANCHOR_SCORE = 3
SUPPORTING_SCORE = 1
UNIQUENESS_MULTIPLIER = 2


@dataclass
class ClassificationResult:
    category: str
    confidence: float  # 0.0 ~ 1.0
    signal_breakdown: dict = field(default_factory=dict)
    matched_keywords: list = field(default_factory=list)


def _score_signal(text: str) -> dict[str, dict]:
    """对一段文本信号，分层计分。

    锚定词 (anchor)   = 3 分 × 独有乘数
    辅助词 (supporting) = 1 分 × 独有乘数

    Returns:
        {category: {'raw_score': float, 'keyword_count': int, 'matched': [str]}}
    """
    if not text:
        return {}

    scores = {}
    for cat, tiers in CATEGORY_KEYWORDS.items():
        matched_anchor = [kw for kw in tiers['anchor'] if kw in text]
        matched_support = [kw for kw in tiers['supporting'] if kw in text]
        if not matched_anchor and not matched_support:
            continue

        raw_score = 0.0
        for kw in matched_anchor:
            score = ANCHOR_SCORE
            if _KEYWORD_UNIQUENESS.get(kw, False):
                score *= UNIQUENESS_MULTIPLIER
            raw_score += score
        for kw in matched_support:
            score = SUPPORTING_SCORE
            if _KEYWORD_UNIQUENESS.get(kw, False):
                score *= UNIQUENESS_MULTIPLIER
            raw_score += score

        all_matched = matched_anchor + matched_support
        scores[cat] = {
            'raw_score': raw_score,
            'keyword_count': len(all_matched),
            'matched': all_matched,
        }
    return scores


def _map_stage_to_category(stage_name):
    """Map a stage prefix (e.g. 园林绿化, 土方) to the most appropriate category."""
    stage_map = [
        ('园林绿化', '装饰装修图'),
        ('绿化施工', '装饰装修图'),
        ('绿化种植', '装饰装修图'),
        ('景观', '装饰装修图'),
        ('装饰装修', '装饰装修图'),
        ('精装修', '装饰装修图'),
        ('土方', '土方工程图'),
        ('基坑', '土方工程图'),
        ('基础', '基础结构图'),
        ('主体', '主体结构图'),
        ('施工准备', '施工计划图'),
        ('临建', '临建设施平面布置图'),
        ('临时', '临建设施平面布置图'),
    ]
    for key, cat in stage_map:
        if key in stage_name:
            return cat
    return '总平面布置图'


STAGE_PATTERN_SCORE = ANCHOR_SCORE * UNIQUENESS_MULTIPLIER  # 6分，与独有锚定词等值


def _extract_stage_signal(text):
    """Detect stage-specific layout plan patterns like 园林绿化施工阶段平面布置图.

    Returns a signal dict in the same format as _score_signal():
        {category: {'raw_score': int, 'keyword_count': int, 'matched': [str]}}
    """
    if not text:
        return {}

    stage_patterns = [
        r'(\S{2,8})施工阶段平面布置图',
        r'(\S{2,8})阶段施工平面布置图',
        r'(\S{2,8})阶段平面布置图',
    ]

    for pattern in stage_patterns:
        match = re.search(pattern, text)
        if match:
            full_match = match.group(0)
            stage_name = match.group(1)
            # Strip leading punctuation or numbers (e.g. "图6 " prefix)
            stage_name = re.sub(r'^[图\d\s]+', '', stage_name)
            if not stage_name:
                continue
            category = _map_stage_to_category(stage_name)
            return {
                category: {
                    'raw_score': STAGE_PATTERN_SCORE,
                    'keyword_count': 1,
                    'matched': [full_match],
                }
            }

    return {}


def _get_top_category(signal_scores: dict) -> str | None:
    """Return the highest-scoring category from a signal's {cat: {raw_score, ...}} dict."""
    if not signal_scores:
        return None
    return max(signal_scores, key=lambda c: signal_scores[c]['raw_score'])


def classify(
    context: str = '',
    figure_name: str = '',
    filename: str = '',
) -> ClassificationResult:
    """多信号融合分类。

    Args:
        context: 文档中的段落上下文文本
        figure_name: 从caption中提取的图名，如 "图1 总平面布置图"
        filename: 图片文件名，如 "image_001.png"

    Returns:
        ClassificationResult with category, confidence, signal_breakdown, matched_keywords
    """
    signals: dict[str, dict[str, dict]] = {}

    if figure_name:
        s = _score_signal(figure_name)
        if s:
            signals['figure_name'] = s
        stage_s = _extract_stage_signal(figure_name)
        if stage_s:
            signals['stage_pattern'] = stage_s

    if context:
        s = _score_signal(context)
        if s:
            signals['context'] = s
        # Also check context for stage patterns (but only if figure_name didn't already find one)
        if 'stage_pattern' not in signals:
            stage_s = _extract_stage_signal(context)
            if stage_s:
                signals['stage_pattern'] = stage_s

    if filename:
        s = _score_signal(filename)
        if s:
            signals['filename'] = s

    # 加权汇总每个类别的总分
    weighted: dict[str, float] = {}
    all_matched_keywords: list[str] = []

    for signal_name, cat_scores in signals.items():
        weight = SIGNAL_WEIGHTS.get(signal_name, 1.0)
        for cat, info in cat_scores.items():
            weighted[cat] = weighted.get(cat, 0) + info['raw_score'] * weight
            all_matched_keywords.extend(info.get('matched', []))

    # 去重关键词
    all_matched_keywords = list(dict.fromkeys(all_matched_keywords))

    if not weighted:
        return ClassificationResult(
            category='其他',
            confidence=0.0,
            signal_breakdown=signals,
            matched_keywords=[],
        )

    max_cat = max(weighted, key=weighted.get)
    total = sum(weighted.values())
    confidence = weighted[max_cat] / total if total > 0 else 0.0

    # 冲突惩罚：图名与上下文指向不同类别时降低置信度
    name_top = _get_top_category(signals.get('figure_name'))
    ctx_top = _get_top_category(signals.get('context'))
    if name_top and ctx_top and name_top != ctx_top:
        confidence *= 0.5

    return ClassificationResult(
        category=max_cat,
        confidence=round(confidence, 4),
        signal_breakdown=signals,
        matched_keywords=all_matched_keywords,
    )
