/** 异议/认领幂等键与决议条目解析：回执丢失后重试时复用同一次操作编号。 */

export type ResolutionOption = {
  value: string
  index?: number
  code?: string
  label: string
}

export function getOperationKey(scope: string): string {
  const storageKey = `diagnose-operation:${scope}`
  const existing = window.sessionStorage.getItem(storageKey)
  if (existing) return existing
  const created =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  window.sessionStorage.setItem(storageKey, created)
  return created
}

export function clearOperationKey(scope: string): void {
  window.sessionStorage.removeItem(`diagnose-operation:${scope}`)
}

export function parseResolutionOptions(content: unknown): ResolutionOption[] {
  const text = String(content ?? '').trim()
  if (!text) return []

  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const rawParts: string[] = []
  for (const line of lines.length ? lines : [text]) {
    rawParts.push(
      ...line
        .split(/\s*[；;]\s*|\s*(?=(?:\d+|[一二三四五六七八九十]+)\s*[.、．)）])/)
        .map((part) => part.trim())
        .filter(Boolean),
    )
  }

  return rawParts.map((part, position) => {
    let rest = part
    let index = position + 1
    const indexMatch = rest.match(/^(?:第)?(\d+|[一二三四五六七八九十]+)\s*[.、．)）条]?\s*/)
    if (indexMatch) {
      const numeric = Number(indexMatch[1])
      if (Number.isFinite(numeric)) index = numeric
      rest = rest.slice(indexMatch[0].length).trim()
    }

    let code = ''
    const leadingCode = rest.match(/^(?:条目|决议|任务)?\s*([A-Z0-9]+)\s*[.、．:：]\s*/)
    if (leadingCode) {
      code = leadingCode[1]
      rest = rest.slice(leadingCode[0].length).trim()
    } else {
      const codeMatch = rest.match(/(?:条目|决议|任务)\s*([A-Z])(?![A-Za-z0-9_:])/)
      if (codeMatch) code = codeMatch[1]
    }

    const value = code || String(index)
    const label = `第${index}条${code ? `（${code}）` : ''}：${rest || part}`
    return { value, index, code: code || undefined, label }
  })
}

export function rowMeetingNumber(row: Record<string, unknown>): string {
  const explicit = row['纪要编号'] || row.meeting_number
  return explicit ? String(explicit) : `M-${String(row.id)}`
}

export function rowTaskNumber(row: Record<string, unknown>): string {
  const explicit = row['任务编号'] || row.task_number || row.task_code
  return explicit ? String(explicit) : `T-${String(row.id)}`
}
