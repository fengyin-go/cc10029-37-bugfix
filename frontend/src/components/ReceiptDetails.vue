<template>
  <div class="receipt-details" :data-testid="testId">
    <h4 v-if="title">{{ title }}</h4>
    <dl>
      <template v-for="(value, key) in visibleFields" :key="key">
        <dt>{{ fieldLabel(String(key)) }}</dt>
        <dd :data-testid="`receipt-field-${key}`">{{ formatValue(value) }}</dd>
      </template>
    </dl>
    <div v-if="receipt.review_item" class="review-box" data-testid="review-item">
      <strong>诊改待复核事项：{{ String((receipt.review_item as Record<string, unknown>).review_no ?? '') }}</strong>
      <p>状态：{{ String((receipt.review_item as Record<string, unknown>).status ?? '待复核') }}</p>
      <p v-if="(receipt.review_item as Record<string, unknown>).submission">
        成果：{{ String((receipt.review_item as Record<string, unknown>).submission) }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  receipt: Record<string, unknown>
  title?: string
  testId?: string
}>(), {
  title: '回执详情',
  testId: 'receipt-panel',
})

const HIDDEN_KEYS = new Set(['id', 'operation_seq', 'kind'])
const LABELS: Record<string, string> = {
  receipt_type: '回执类型',
  receipt_no: '回执编号',
  request_id: '同一次操作请求编号',
  status: '处理状态',
  meeting_id: '纪要ID',
  meeting_number: '纪要编号',
  resolution_index: '决议条目序号',
  resolution_code: '决议条目编号',
  resolution_entry: '注明的决议条目',
  objector: '异议人',
  objection_reason: '异议内容',
  task_id: '原任务ID',
  original_task_id: '原任务ID',
  task_number: '原任务编号',
  original_task_number: '原任务编号',
  claimant: '办理人',
  handling_instruction: '办理指引',
  handling_result: '异议处理结果',
  original_result: '原处理结果',
  original_message: '原处理结果',
  message: '处理结果',
  claim_receipt_no: '认领回执编号',
  objection_receipt_no: '异议回执编号',
  review_no: '诊改待复核事项编号',
  qualification_decision: '资格冲突裁决',
  granted: '是否取得资格',
  distribution_restored: '分发资格已恢复',
}

const visibleFields = computed(() =>
  Object.fromEntries(
    Object.entries(props.receipt).filter(([key, value]) =>
      !HIDDEN_KEYS.has(key)
      && value !== null
      && value !== ''
      && typeof value !== 'object',
    ),
  ),
)

function fieldLabel(key: string): string {
  return LABELS[key] ?? key
}

function formatValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
</script>
