"""
统一图纸分类服务 - 多信号融合 + 置信度评分

信号源权重:
  figure_name   5.0x  (图名直接包含类别名)
  stage_pattern 5.0x  (X阶段施工平面布置图 → 对应阶段类别)
  context       1.0x  (文档段落上下文)
  filename      0.8x  (文件名，信号弱)
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

# 统一关键词表 — 合并两套关键词，去掉裸单字词
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    '周边环境图': [
        '周边环境', '项目区位', '现场踏勘', '环境图', '区位图',
        '地理位置', '周边概况', '踏勘', '周边现状', '周边地貌',
    ],
    '进度计划图': [
        '进度计划', '横道图', '开竣工', '施工进度', '进度图',
        '工期安排', '进度表', '甘特图', '网络图',
    ],
    '分区规划图': [
        '分区规划', '规划图', '阶段划分', '分区示意', '分区图',
    ],
    '总平面布置图': [
        '总平面布置', '施工总平面', '平面布置图', '总平面', '总平图',
        '总平布置', '场地布置',
    ],
    '基础结构图': [
        '基础结构', '基础图', '结构布置', '桩基', '基础平面',
        '基础施工', '桩位', '筏板', '承台',
    ],
    '临时用电布置图': [
        '临时用电', '用电布置', '配电', '临电图', '用电图',
        '临电', '现场用电', '配电房', '配电箱',
    ],
    '临时用水布置图': [
        '临时用水', '用水布置', '给水', '排水', '临水图',
        '临水', '现场用水', '供水',
    ],
    '土方工程图': [
        '土方工程', '土方开挖', '基坑', '土方图', '开挖图',
        '挖方', '边坡', '支护', '土钉墙',
    ],
    '主体结构图': [
        '主体结构', '结构层', '主体图', '主体施工', '结构施工',
        '框架', '剪力墙', '柱网', '梁板', '结构平面',
    ],
    '装饰装修图': [
        '装饰装修', '装修图', '装饰图', '装修做法', '精装修',
        '外立面', '内装', '园林绿化', '绿化种植', '景观施工',
        '绿化施工', '硬质铺装', '铺装',
    ],
    '施工计划图': [
        '施工计划', '施工安排', '计划图', '施工部署', '总体安排',
        '施工组织',
    ],
    '临建设施平面布置图': [
        '临建设施', '临建平面', '临建布置', '活动板房', '临建图',
        '临设', '临时设施', '办公区', '生活区', '宿舍', '食堂',
        '门卫', '洗车', '标养室', '办公室',
    ],
    '施工分区图': [
        '施工分区', '分区施工', '施工段划分', '施工段', '流水段',
    ],
}

# 信号权重
SIGNAL_WEIGHTS = {
    'figure_name': 5.0,
    'stage_pattern': 5.0,
    'context': 1.0,
    'filename': 0.8,
}


@dataclass
class ClassificationResult:
    category: str
    confidence: float  # 0.0 ~ 1.0
    signal_breakdown: dict = field(default_factory=dict)
    matched_keywords: list = field(default_factory=list)


def _score_signal(text: str) -> dict[str, dict]:
    """对一段文本信号，计算每个类别的关键词匹配得分。

    Returns:
        {category: {'raw_score': int, 'keyword_count': int, 'matched': [str]}}
    """
    if not text:
        return {}

    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in text]
        if matched:
            raw_score = sum(len(kw) for kw in matched)
            scores[cat] = {
                'raw_score': raw_score,
                'keyword_count': len(matched),
                'matched': matched,
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
                    'raw_score': len(full_match),
                    'keyword_count': 1,
                    'matched': [full_match],
                }
            }

    return {}


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

    return ClassificationResult(
        category=max_cat,
        confidence=round(confidence, 4),
        signal_breakdown=signals,
        matched_keywords=all_matched_keywords,
    )
