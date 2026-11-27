/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ReceiptRecord = {
  id?: number
  receipt_type?: string
  kind?: string
  receipt_no?: string
  request_id?: string
  status?: string
  message?: string
  original_message?: string
  original_result?: string
  [key: string]: unknown
}

export type ReviewItem = {
  id: number
  review_no: string
  status: string
  task_id: number
  task_number?: string
  meeting_number?: string
  resolution_entry?: string
  claim_receipt_no?: string
  objection_receipt_no?: string
  submission?: string
  [key: string]: unknown
}

export type ActionResult = {
  ok: boolean
  message: string
  entry?: EntryRow | null
  receipt?: ReceiptRecord | null
  receipts?: ReceiptRecord[] | null
  review_item?: ReviewItem | null
  conflict?: Record<string, unknown> | null
  idempotent_replay?: boolean
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}
