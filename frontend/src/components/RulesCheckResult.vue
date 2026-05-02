<template>
  <div class="rules-check">
    <div class="summary-bar">
      <div class="summary-item ok">
        <span class="summary-num">{{ stats.compliant }}</span>
        <span class="summary-label">合规</span>
      </div>
      <div class="summary-item warn">
        <span class="summary-num">{{ stats.nonCompliant }}</span>
        <span class="summary-label">不合规</span>
      </div>
      <div class="summary-item info">
        <span class="summary-num">{{ stats.undetectable }}</span>
        <span class="summary-label">无法检测</span>
      </div>
    </div>

    <div class="score-badge">
      <div class="score-ring">
        <svg viewBox="0 0 64 64" width="64" height="64">
          <circle cx="32" cy="32" r="28" fill="none" stroke="#e2e8f0" stroke-width="5"/>
          <circle cx="32" cy="32" r="28" fill="none" :stroke="scoreColor" stroke-width="5"
            stroke-dasharray="175.9" :stroke-dashoffset="175.9 - (175.9 * totalScore / 100)"
            stroke-linecap="round" transform="rotate(-90 32 32)"/>
        </svg>
        <span class="score-text" :style="{ color: scoreColor }">{{ totalScore }}</span>
      </div>
      <span class="score-label">总分</span>
    </div>

    <div class="rule-list">
      <div v-for="(rule, idx) in results" :key="idx" class="rule-item">
        <div class="rule-status" :class="rule.status">
          <span v-if="rule.status === '合规'" class="status-icon ok">✓</span>
          <span v-else-if="rule.status === '不合规'" class="status-icon warn">!</span>
          <span v-else class="status-icon info">?</span>
        </div>
        <div class="rule-body">
          <div class="rule-header">
            <span class="rule-id">{{ formatRuleId(rule.rule_id) }}</span>
            <el-tag :type="getSeverityType(rule.severity)" size="small" effect="dark">
              {{ rule.severity }}
            </el-tag>
          </div>
          <div class="rule-desc">{{ getFullRuleDescription(rule) }}</div>
          <div class="rule-msg" v-if="rule.status !== '合规'">{{ rule.message }}</div>
        </div>
        <div class="rule-deduction" v-if="calculateDeduction(rule.severity, rule.status) > 0">
          -{{ calculateDeduction(rule.severity, rule.status) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface RuleResult {
  rule_id: string
  category: string
  description?: string
  severity: string
  status: string
  message: string
  sub_rules?: RuleResult[]
}

const props = defineProps<{ results: RuleResult[] }>()

const stats = computed(() => {
  if (!props.results?.length) return { compliant: 0, nonCompliant: 0, undetectable: 0, failed: 0 }
  return props.results.reduce((acc, r) => {
    if (r.status === '合规') acc.compliant++
    else if (r.status === '不合规') acc.nonCompliant++
    else if (r.status === '无法检测') acc.undetectable++
    else acc.failed++
    return acc
  }, { compliant: 0, nonCompliant: 0, undetectable: 0, failed: 0 })
})

const totalScore = computed(() => {
  if (!props.results?.length) return 100
  const deduction = props.results.reduce((sum, r) => sum + calculateDeduction(r.severity, r.status), 0)
  return Math.max(0, 100 - deduction)
})

const scoreColor = computed(() => {
  if (totalScore.value >= 80) return '#22c55e'
  if (totalScore.value >= 60) return '#f59e0b'
  return '#ef4444'
})

const formatRuleId = (id: string) => id ? id.toString() : ''

const getFullRuleDescription = (rule: RuleResult) => {
  let desc = rule.description || ''
  if (rule.sub_rules?.length) {
    desc += ' | ' + rule.sub_rules.map(sr => sr.description).join('; ')
  }
  return desc
}

const getSeverityType = (s: string): 'danger' | 'warning' | 'info' => {
  if (s === '严重') return 'danger'
  if (s === '重要') return 'warning'
  return 'info'
}

const calculateDeduction = (severity: string, status: string) => {
  if (status !== '不合规') return 0
  if (severity === '严重') return 10
  if (severity === '重要') return 5
  return 2
}
</script>

<style scoped>
.rules-check { display: flex; flex-direction: column; gap: 12px; }

.summary-bar {
  display: flex; gap: 8px;
}
.summary-item {
  flex: 1; text-align: center; padding: 8px 4px; border-radius: 8px;
}
.summary-item.ok { background: #f0fdf4; }
.summary-item.warn { background: #fef2f2; }
.summary-item.info { background: #f0f9ff; }
.summary-num { font-size: 20px; font-weight: 700; display: block; }
.summary-item.ok .summary-num { color: #16a34a; }
.summary-item.warn .summary-num { color: #dc2626; }
.summary-item.info .summary-num { color: #2563eb; }
.summary-label { font-size: 11px; color: #64748b; }

.score-badge {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.score-ring { position: relative; display: flex; align-items: center; justify-content: center; }
.score-text {
  position: absolute; font-size: 18px; font-weight: 800;
}
.score-label { font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }

.rule-list { display: flex; flex-direction: column; gap: 1px; }
.rule-item {
  display: flex; gap: 10px; padding: 10px; border-radius: 6px;
  background: #f8fafc; transition: background .15s;
}
.rule-item:hover { background: #f1f5f9; }

.rule-status { flex-shrink: 0; }
.status-icon {
  display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%; font-size: 11px; font-weight: 700;
}
.status-icon.ok { background: #dcfce7; color: #16a34a; }
.status-icon.warn { background: #fee2e2; color: #dc2626; }
.status-icon.info { background: #dbeafe; color: #2563eb; }

.rule-body { flex: 1; min-width: 0; }
.rule-header { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
.rule-id { font-size: 11px; font-weight: 700; color: #64748b; font-family: monospace; }
.rule-desc { font-size: 12px; color: #334155; line-height: 1.5; }
.rule-msg { font-size: 11px; color: #dc2626; margin-top: 2px; }

.rule-deduction {
  font-size: 14px; font-weight: 700; color: #dc2626; flex-shrink: 0;
  align-self: center;
}
</style>
