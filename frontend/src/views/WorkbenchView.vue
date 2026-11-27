<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div v-if="isWorkflow" class="workflow-bar" data-testid="workflow-bar">
      <label class="operator-field">
        <span>当前办理人</span>
        <input v-model="currentOperator" data-testid="current-operator" @change="persistOperator" />
      </label>
      <div class="receipt-lookup">
        <input
          v-model="receiptQuery"
          data-testid="receipt-lookup-input"
          placeholder="输入异议/认领回执编号或同一次操作请求编号"
          @keyup.enter="searchReceipt()"
        />
        <button class="btn" data-testid="receipt-lookup-button" type="button" @click="searchReceipt()">
          查回执/原任务
        </button>
      </div>
    </div>

    <div v-if="lookupError" class="error-text" data-testid="receipt-lookup-error">{{ lookupError }}</div>
    <div v-if="lookupResult" class="lookup-result" data-testid="receipt-lookup-result">
      <ReceiptDetails :receipt="lookupResult" title="回执查询结果" test-id="lookup-receipt" />
      <button
        v-if="lookupTaskId"
        class="btn primary"
        data-testid="open-receipt-task"
        type="button"
        @click="openLookupTask"
      >
        按回执打开原任务并提交成果
      </button>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <div v-if="claimError" class="conflict-banner" data-testid="claim-conflict">
      <span>{{ claimError.message }}</span>
      <span class="banner-actions">
        <button class="btn" data-testid="retry-claim" type="button" @click="retryClaim">
          重试同一次认领请求
        </button>
        <button class="btn primary" data-testid="new-claim" type="button" @click="newClaim">
          争议解决后重新领取
        </button>
      </span>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th v-if="isWorkflow">回执与办理资格</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :data-testid="`row-${row.id}`"
          :data-status="String(row.status)"
          :class="{ highlight: Number(row.id) === highlightTaskId }"
        >
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <strong>{{ row.status }}</strong>
            <div v-if="row.objection_status" class="sub-status" data-testid="row-objection-status">
              {{ row.objection_status }}
            </div>
          </td>
          <td v-if="isWorkflow" class="workflow-cell" :data-testid="`workflow-state-${row.id}`">
            <div v-if="row.qualification_state">资格：{{ row.qualification_state }}</div>
            <div v-if="row.distribution_qualification">分发资格：{{ row.distribution_qualification }}</div>
            <div v-if="row.claim_receipt_no">认领回执：{{ row.claim_receipt_no }}</div>
            <div v-if="row.objection_receipt_no">异议回执：{{ row.objection_receipt_no }}</div>
            <div v-if="row.review_no">待复核：{{ row.review_no }}</div>
            <div v-if="Array.isArray(row.review_item_nos)">
              <span v-for="no in row.review_item_nos" :key="`review-${String(no)}`" class="receipt-chip review-chip">
                待复核 {{ String(no) }}
              </span>
            </div>
            <div v-if="Array.isArray(row.objection_receipt_nos)">
              <span v-for="no in row.objection_receipt_nos" :key="String(no)" class="receipt-chip">{{ String(no) }}</span>
            </div>
          </td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              :disabled="claimBusyId === Number(row.id) && action === '认领任务'"
              @click="handleAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + (isWorkflow ? 3 : 2)" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input
            v-model="createValues[field]"
            :data-testid="`create-${field}`"
            :required="['会议主题', '参会人员', '召开日期', '任务描述', '承接方案', '执行人员'].includes(field)"
          />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="objectionDialog" class="modal-backdrop" data-testid="objection-modal">
      <form class="modal" @submit.prevent="submitObjection">
        <h3>对已分发纪要提出条目异议</h3>
        <p>
          纪要 <strong>{{ rowMeetingNumber(objectionDialog.row) }}</strong>
          （ID {{ objectionDialog.row.id }}）不会退回草稿，仍按已分发纪要查阅。
        </p>
        <label class="create-field">
          <span>异议人</span>
          <input v-model="objectionDialog.objector" data-testid="objection-objector" />
        </label>
        <label class="create-field">
          <span>异议对应的决议条目</span>
          <select v-model="objectionDialog.resolution" data-testid="objection-resolution">
            <option value="" disabled>请选择注明的决议条目</option>
            <option v-for="option in resolutionOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="create-field">
          <span>异议内容</span>
          <textarea
            v-model="objectionDialog.reason"
            data-testid="objection-reason"
            rows="4"
            placeholder="请说明对哪项决议有异议"
          />
        </label>
        <p class="request-line">
          同一次异议操作编号：<code data-testid="objection-request-id">{{ objectionDialog.requestId }}</code>
        </p>
        <p v-if="objectionDialog.error" class="error-text" data-testid="objection-error">
          {{ objectionDialog.error }}
        </p>
        <div class="page-actions">
          <button class="btn" type="button" @click="cancelObjection">取消</button>
          <button
            class="btn primary"
            data-testid="submit-objection"
            type="submit"
            :disabled="objectionDialog.busy || !objectionDialog.resolution"
          >
            {{ objectionDialog.busy ? '提交中…' : '确认异议并取回执' }}
          </button>
          <button
            v-if="objectionDialog.error"
            class="btn"
            data-testid="retry-objection"
            type="button"
            @click="submitObjection"
          >
            重试同一次异议
          </button>
        </div>
      </form>
    </div>

    <div v-if="completeDialog" class="modal-backdrop" data-testid="complete-objection-modal">
      <form class="modal" @submit.prevent="submitCompleteObjection">
        <h3>异议办理完成并恢复资格</h3>
        <label class="create-field">
          <span>异议回执编号</span>
          <input v-model="completeDialog.receiptNo" data-testid="complete-receipt-no" />
        </label>
        <label class="create-field">
          <span>办理结果</span>
          <textarea
            v-model="completeDialog.handlingResult"
            data-testid="complete-result"
            rows="4"
            placeholder="例如：异议已核对，按原决议恢复分发和认领资格"
          />
        </label>
        <p class="request-line">
          同一次办理请求编号：<code>{{ completeDialog.requestId }}</code>
        </p>
        <p v-if="completeDialog.error" class="error-text">{{ completeDialog.error }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="completeDialog = null">取消</button>
          <button class="btn primary" data-testid="submit-complete-objection" type="submit">
            办理完成并恢复资格
          </button>
        </div>
      </form>
    </div>

    <div v-if="resultDialog" class="modal-backdrop" data-testid="submit-result-modal">
      <form class="modal" @submit.prevent="submitResult">
        <h3>按回执打开原任务提交成果</h3>
        <p>
          原任务编号 <strong>{{ rowTaskNumber(resultDialog.row) }}</strong>
          （ID {{ resultDialog.row.id }}）
        </p>
        <label class="create-field">
          <span>认领回执编号（同一次认领请求）</span>
          <input v-model="resultDialog.claimReceiptNo" data-testid="result-claim-receipt" />
        </label>
        <label class="create-field">
          <span>异议回执编号</span>
          <input v-model="resultDialog.objectionReceiptNo" data-testid="result-objection-receipt" />
        </label>
        <label class="create-field">
          <span>试教记录/成果内容</span>
          <textarea
            v-model="resultDialog.content"
            data-testid="result-content"
            rows="5"
            placeholder="填写已完成的试教记录、材料编号或成果说明"
          />
        </label>
        <p class="request-line">
          同一次提交请求编号：<code data-testid="result-request-id">{{ resultDialog.requestId }}</code>
        </p>
        <p v-if="resultDialog.error" class="error-text" data-testid="result-error">{{ resultDialog.error }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="resultDialog = null">取消</button>
          <button class="btn primary" data-testid="submit-result-confirm" type="submit" :disabled="resultDialog.busy">
            {{ resultDialog.busy ? '提交中…' : '提交并生成诊改待复核事项' }}
          </button>
          <button
            v-if="resultDialog.error"
            class="btn"
            data-testid="retry-result"
            type="button"
            @click="submitResult"
          >
            重试同一次提交
          </button>
        </div>
      </form>
    </div>

    <div v-if="receiptDialog" class="modal-backdrop" data-testid="receipt-modal">
      <div class="modal">
        <h3>{{ receiptDialog.title }}</h3>
        <p
          :class="receiptDialog.result.ok ? 'success-text' : 'error-text'"
          data-testid="receipt-message"
        >
          {{ receiptDialog.result.message }}
        </p>
        <ReceiptDetails
          v-if="receiptDialog.result.receipt"
          :receipt="(receiptDialog.result.receipt ?? {}) as Record<string, unknown>"
          :test-id="receiptTestId"
        />
        <div v-if="receiptDialog.result.review_item" class="review-box" data-testid="review-item">
          <strong>诊改待复核事项：{{ receiptDialog.result.review_item.review_no }}</strong>
          <p>状态：{{ receiptDialog.result.review_item.status }}</p>
          <p>原任务编号：{{ receiptDialog.result.review_item.task_number }}</p>
          <p v-if="receiptDialog.result.review_item.submission">
            试教记录/成果：{{ receiptDialog.result.review_item.submission }}
          </p>
        </div>
        <div class="page-actions">
          <button class="btn" data-testid="close-receipt" type="button" @click="closeReceipt">关闭</button>
          <button
            v-if="canOpenDialogTask"
            class="btn primary"
            data-testid="receipt-open-task"
            type="button"
            @click="openDialogTask"
          >
            在诊改任务中打开原任务
          </button>
          <button
            v-if="canRenewClaim"
            class="btn primary"
            data-testid="receipt-new-claim"
            type="button"
            @click="renewClaimFromReceipt"
          >
            争议解决后重新领取
          </button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="successMessage" class="success-text" data-testid="action-success">{{ successMessage }}</span>
      <span v-if="errorMessage" class="error-text" data-testid="action-error">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ReceiptDetails from '@/components/ReceiptDetails.vue'
import {
  createEntry,
  downloadEntries,
  listEntries,
  lookupReceipt,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import type { ActionResult, EntryRow } from '@/data/types'
import {
  clearOperationKey,
  getOperationKey,
  parseResolutionOptions,
  rowMeetingNumber,
  rowTaskNumber,
} from '@/domain/workflow'

const props = defineProps<{ moduleKey: string }>()
const route = useRoute()
const router = useRouter()
const meta = moduleMeta(props.moduleKey)

const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

const isMeeting = computed(() => props.moduleKey === 'review_meeting')
const isTask = computed(() => props.moduleKey === 'improve_task')
const isWorkflow = computed(() => isMeeting.value || isTask.value)

const currentOperator = ref(window.localStorage.getItem('diagnose-operator') || '乙')
function persistOperator() {
  window.localStorage.setItem('diagnose-operator', currentOperator.value || '乙')
}

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

const receiptQuery = ref('')
const lookupResult = ref<Record<string, unknown> | null>(null)
const lookupError = ref('')
const highlightTaskId = ref<number | null>(null)

const claimBusyId = ref<number | null>(null)
const claimError = ref<{ row: EntryRow; message: string } | null>(null)

type ObjectionDialogState = {
  row: EntryRow
  requestId: string
  objector: string
  resolution: string
  reason: string
  error: string
  busy: boolean
}
const objectionDialog = ref<ObjectionDialogState | null>(null)
const resolutionOptions = computed(() =>
  objectionDialog.value ? parseResolutionOptions(objectionDialog.value.row['决议事项']) : [],
)

type CompleteDialogState = {
  row: EntryRow
  requestId: string
  receiptNo: string
  handlingResult: string
  error: string
}
const completeDialog = ref<CompleteDialogState | null>(null)

type ResultDialogState = {
  row: EntryRow
  requestId: string
  content: string
  claimReceiptNo: string
  objectionReceiptNo: string
  error: string
  busy: boolean
}
const resultDialog = ref<ResultDialogState | null>(null)

const receiptDialog = ref<{ title: string; result: ActionResult } | null>(null)
const receiptTestId = computed(() => {
  const type = String(receiptDialog.value?.result.receipt?.receipt_type ?? '')
  if (type.includes('异议')) return 'objection-receipt'
  if (type.includes('认领')) return 'claim-receipt'
  return 'workflow-receipt'
})
const dialogTaskId = computed(() => {
  const receipt = receiptDialog.value?.result.receipt as Record<string, unknown> | undefined
  const review = receiptDialog.value?.result.review_item as Record<string, unknown> | undefined
  const id = receipt?.task_id ?? receipt?.original_task_id ?? review?.task_id
  return id === undefined || id === null ? null : Number(id)
})
const canOpenDialogTask = computed(() => dialogTaskId.value !== null)
const canRenewClaim = computed(() =>
  String(receiptDialog.value?.result.receipt?.status ?? '').includes('冻结')
  || String(receiptDialog.value?.result.message ?? '').includes('异议优先'),
)

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, { ...filters.value, size: '200' })
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function genericAction(action: string, row: EntryRow) {
  const result = await applyAction(meta.key, Number(row.id), action, {
    operator: currentOperator.value,
  })
  if (!result.ok) throw new Error(result.message)
  successMessage.value = result.message
  if (result.receipt || result.review_item) {
    receiptDialog.value = { title: `${meta.entity}处理回执`, result }
  }
  await reload()
}

async function handleAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  successMessage.value = ''
  claimError.value = null
  try {
    if (isMeeting.value && action === '提出异议') return openObjection(row)
    if (isMeeting.value && (action === '异议办理完成' || action === '办理异议')) {
      return openCompleteObjection(row)
    }
    if (isTask.value && action === '认领任务') return await submitClaim(row)
    if (isTask.value && (action === '提交成果' || action === '提交试教记录')) return openResultDialog(row)
    await genericAction(action, row)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

function openObjection(row: EntryRow) {
  const options = parseResolutionOptions(row['决议事项'])
  objectionDialog.value = {
    row,
    requestId: getOperationKey(`objection:${row.id}`),
    objector: currentOperator.value || '乙',
    resolution: options.length === 1 ? options[0].value : '',
    reason: '',
    error: '',
    busy: false,
  }
}

function cancelObjection() {
  if (objectionDialog.value) clearOperationKey(`objection:${objectionDialog.value.row.id}`)
  objectionDialog.value = null
}

async function submitObjection() {
  const dialog = objectionDialog.value
  if (!dialog) return
  dialog.busy = true
  dialog.error = ''
  const option = resolutionOptions.value.find((item) => item.value === dialog.resolution)
  try {
    const result = await applyAction('review_meeting', Number(dialog.row.id), '提出异议', {
      request_id: dialog.requestId,
      operator: dialog.objector,
      objector: dialog.objector,
      resolution_index: option?.index,
      resolution_code: option?.code ?? (/^[A-Za-z]+$/.test(dialog.resolution) ? dialog.resolution : undefined),
      resolution_entry: option?.label,
      objection_reason: dialog.reason,
      remark: dialog.reason,
    })
    if (!result.ok) {
      dialog.error = result.message
      if (result.receipt) {
        clearOperationKey(`objection:${dialog.row.id}`)
        objectionDialog.value = null
        receiptDialog.value = { title: '异议请求处理结果', result }
      }
      return
    }
    clearOperationKey(`objection:${dialog.row.id}`)
    objectionDialog.value = null
    currentOperator.value = dialog.objector
    persistOperator()
    receiptDialog.value = { title: '异议回执', result }
    await reload()
  } catch (error) {
    dialog.error = `${error instanceof Error ? error.message : '回执请求未送达'}；可直接重试同一次异议操作。`
  } finally {
    dialog.busy = false
  }
}

function lastObjectionNo(row: EntryRow): string {
  if (row.objection_receipt_no) return String(row.objection_receipt_no)
  const list = row.objection_receipt_nos
  if (Array.isArray(list) && list.length) return String(list[list.length - 1])
  return ''
}

function openCompleteObjection(row: EntryRow) {
  completeDialog.value = {
    row,
    requestId: getOperationKey(`complete-objection:${row.id}:${lastObjectionNo(row)}`),
    receiptNo: lastObjectionNo(row),
    handlingResult: '异议已核对，按原决议恢复分发资格和对应任务办理资格',
    error: '',
  }
}

async function submitCompleteObjection() {
  const dialog = completeDialog.value
  if (!dialog) return
  dialog.error = ''
  try {
    const result = await applyAction('review_meeting', Number(dialog.row.id), '异议办理完成', {
      request_id: dialog.requestId,
      objection_receipt_no: dialog.receiptNo,
      receipt_no: dialog.receiptNo,
      handling_result: dialog.handlingResult,
      remark: dialog.handlingResult,
    })
    if (!result.ok) {
      dialog.error = result.message
      return
    }
    clearOperationKey(`complete-objection:${dialog.row.id}:${dialog.receiptNo}`)
    completeDialog.value = null
    receiptDialog.value = { title: '异议办理与资格恢复结果', result }
    await reload()
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '操作失败，可重试同一次办理'
  }
}

async function submitClaim(row: EntryRow, renew = false) {
  claimError.value = null
  const operator = currentOperator.value.trim() || '乙'
  const scope = `claim:${row.id}:${operator}`
  if (renew) clearOperationKey(scope)
  const requestId = getOperationKey(scope)
  claimBusyId.value = Number(row.id)
  try {
    const result = await applyAction('improve_task', Number(row.id), '认领任务', {
      request_id: requestId,
      operator,
      claimant: operator,
    })
    if (result.ok) {
      clearOperationKey(scope)
      successMessage.value = result.message
      receiptDialog.value = { title: '认领回执', result }
      await reload()
    } else {
      // 不清除 scope：按钮“重试同一次认领请求”必须返回同一个原处理结果。
      claimError.value = { row, message: result.message }
      if (result.receipt) receiptDialog.value = { title: '认领请求处理结果', result }
      await reload()
    }
  } catch (error) {
    claimError.value = {
      row,
      message: `${error instanceof Error ? error.message : '认领回执中断'}；服务器可能已受理，可重试同一次认领请求查询原任务编号和结果。`,
    }
  } finally {
    claimBusyId.value = null
  }
}

function retryClaim() {
  if (claimError.value) void submitClaim(claimError.value.row)
}

function newClaim() {
  if (!claimError.value) return
  const row = claimError.value.row
  claimError.value = null
  void submitClaim(row, true)
}

function openResultDialog(row: EntryRow, presetObjection = '') {
  const queryReceipt = typeof route.query.receipt === 'string' ? route.query.receipt : ''
  const objection = presetObjection
    || String(row.objection_receipt_no ?? '')
    || (queryReceipt.startsWith('YY') ? queryReceipt : '')
  resultDialog.value = {
    row,
    requestId: getOperationKey(`submit-result:${row.id}`),
    content: String(row.last_submission ?? ''),
    claimReceiptNo: String(row.claim_receipt_no ?? ''),
    objectionReceiptNo: objection,
    error: '',
    busy: false,
  }
}

async function submitResult() {
  const dialog = resultDialog.value
  if (!dialog) return
  dialog.busy = true
  dialog.error = ''
  try {
    const result = await applyAction('improve_task', Number(dialog.row.id), '提交成果', {
      request_id: dialog.requestId,
      claim_receipt_no: dialog.claimReceiptNo,
      objection_receipt_no: dialog.objectionReceiptNo,
      receipt_no: dialog.objectionReceiptNo,
      submission: dialog.content,
      result_content: dialog.content,
      试教记录: dialog.content,
      operator: currentOperator.value,
    })
    if (!result.ok) {
      dialog.error = result.message
      if (result.receipt) receiptDialog.value = { title: '成果提交拦截结果', result }
      return
    }
    clearOperationKey(`submit-result:${dialog.row.id}`)
    resultDialog.value = null
    receiptDialog.value = { title: '试教记录提交与待复核回执', result }
    await reload()
  } catch (error) {
    dialog.error = `${error instanceof Error ? error.message : '提交回执中断'}；可重试同一次提交，不会生成重复待复核事项。`
  } finally {
    dialog.busy = false
  }
}

async function searchReceipt() {
  const reference = receiptQuery.value.trim()
  if (!reference) return
  lookupError.value = ''
  lookupResult.value = null
  try {
    lookupResult.value = await lookupReceipt(reference)
    const taskId = Number(lookupResult.value.task_id ?? lookupResult.value.original_task_id)
    if (Number.isFinite(taskId) && taskId > 0) highlightTaskId.value = taskId
  } catch (error) {
    lookupError.value = error instanceof Error ? error.message : '未查到回执'
  }
}

const lookupTaskId = computed<number | null>(() => {
  const raw = lookupResult.value?.task_id ?? lookupResult.value?.original_task_id
  const id = Number(raw)
  return Number.isFinite(id) && id > 0 ? id : null
})

function openLookupTask() {
  if (!lookupResult.value || lookupTaskId.value === null) return
  const receiptNo = String(
    lookupResult.value.receipt_no
      ?? lookupResult.value.objection_receipt_no
      ?? lookupResult.value.request_id
      ?? '',
  )
  if (isMeeting.value) {
    void router.push({
      path: '/improve_task',
      query: { task: String(lookupTaskId.value), receipt: receiptNo },
    })
    return
  }
  const row = rows.value.find((item) => Number(item.id) === lookupTaskId.value)
  if (row) {
    const type = String(lookupResult.value.receipt_type ?? '')
    const objectionNo = String(
      lookupResult.value.objection_receipt_no ?? (type.includes('异议') ? receiptNo : ''),
    )
    openResultDialog(row, objectionNo)
  }
}

function closeReceipt() {
  receiptDialog.value = null
}

function rowFromReceipt(receipt: Record<string, unknown> | null | undefined): EntryRow | undefined {
  const id = Number(receipt?.task_id ?? receipt?.original_task_id)
  return rows.value.find((row) => Number(row.id) === id)
}

function openDialogTask() {
  const receipt = receiptDialog.value?.result.receipt as Record<string, unknown> | undefined
  const review = receiptDialog.value?.result.review_item as Record<string, unknown> | undefined
  const id = dialogTaskId.value
  const receiptNo = String(receipt?.receipt_no ?? review?.objection_receipt_no ?? '')
  if (id === null) return
  if (isMeeting.value) {
    void router.push({ path: '/improve_task', query: { task: String(id), receipt: receiptNo } })
    return
  }
  const row = rows.value.find((item) => Number(item.id) === id)
  if (row) {
    const isObjection = String(receipt?.receipt_type ?? '').includes('异议')
    openResultDialog(row, isObjection ? receiptNo : String(receipt?.objection_receipt_no ?? ''))
  }
}

function renewClaimFromReceipt() {
  const receipt = receiptDialog.value?.result.receipt as Record<string, unknown> | undefined
  const row = rowFromReceipt(receipt)
  receiptDialog.value = null
  if (row) void submitClaim(row, true)
}

onMounted(async () => {
  await reload()
  const queryTask = Number(route.query.task)
  if (Number.isFinite(queryTask) && queryTask > 0) highlightTaskId.value = queryTask

  const queryReceipt = route.query.receipt
  if (typeof queryReceipt === 'string' && queryReceipt.trim()) {
    receiptQuery.value = queryReceipt
    await searchReceipt()
    if (isTask.value) {
      const id = lookupTaskId.value ?? (Number.isFinite(queryTask) ? queryTask : null)
      const row = id === null ? undefined : rows.value.find((item) => Number(item.id) === id)
      if (row) {
        const found = lookupResult.value
        const type = String(found?.receipt_type ?? '')
        const objectionNo = String(
          found?.objection_receipt_no
            ?? (type.includes('异议') ? queryReceipt : '')
            ?? (queryReceipt.startsWith('YY') ? queryReceipt : ''),
        )
        openResultDialog(row, objectionNo)
      }
    }
  }
})
</script>

<style scoped>
.workflow-bar {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.operator-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.operator-field input { padding: 7px 9px; border: 1px solid var(--border); border-radius: 6px; min-width: 160px; }
.receipt-lookup { display: flex; gap: 8px; flex: 1; min-width: 280px; justify-content: flex-end; }
.receipt-lookup input { flex: 1; max-width: 460px; padding: 7px 9px; border: 1px solid var(--border); border-radius: 6px; }
.lookup-result, .review-box {
  background: #fff;
  border: 1px solid #b7d4ff;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.review-box { border-color: #86efac; background: #f0fdf4; margin-top: 10px; }
.conflict-banner {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.banner-actions { display: flex; gap: 8px; }
.workflow-cell { min-width: 210px; font-size: 12px; line-height: 1.55; }
.sub-status { color: #b45309; font-size: 12px; margin-top: 2px; }
.receipt-chip {
  display: inline-block;
  background: #eef4ff;
  border: 1px solid #b7d4ff;
  border-radius: 999px;
  padding: 1px 7px;
  margin: 2px 4px 0 0;
}
.review-chip { background: #f0fdf4; border-color: #86efac; color: #067647; }
.highlight { outline: 2px solid #1f6feb; outline-offset: -2px; }
.request-line { font-size: 12px; color: var(--muted); word-break: break-all; }
.success-text { color: #067647; }
.create-field textarea {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  font: inherit;
}
:deep(.receipt-details dl) { display: grid; grid-template-columns: 130px 1fr; gap: 6px 10px; }
:deep(.receipt-details dt) { color: var(--muted); font-size: 12px; }
:deep(.receipt-details dd) { margin: 0; font-size: 13px; word-break: break-word; }
</style>
