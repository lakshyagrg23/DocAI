export type AnswerStatus = 'answered' | 'partial' | 'conflict' | 'abstained'
export type ClauseStatus = 'in_force' | 'superseded' | 'future' | 'deleted'

export interface Chat {
  chat_id: string
  title: string
  created_at: string
  as_of_date: string | null
  language: string
  doc_scope: string[] | null
}

export interface Source {
  n: number
  span_id: string
  clause_id: string
  doc_id: string
  doc_name: string
  doc_sub: string
  clause_label: string
  page: number
  pages: number | null
  page_width: number | null
  page_height: number | null
  bboxes: number[][]
  text: string
  row: Record<string, string> | null
  ocr: boolean
  ocr_conf: number | null
  status: ClauseStatus
  effective: string | null
}

export interface Checks {
  spans_valid: boolean
  numbers_ok: boolean
  quote_ok: boolean
  version_ok: boolean
  hhem: number | null
  conflict_ids: string[]
}

export interface Claim {
  text: string
  span_ids: string[]
  verdict: 'supported' | 'unsupported' | 'contradicted'
  checks: Checks
  reason: string | null
}

export interface DisagreementSide {
  span_id: string
  clause_id: string
  doc: string
  doc_title?: string | null
  doc_name?: string | null
  clause_label?: string | null
  page: number | null
  status: ClauseStatus
  value: string
  op: string
  attribute: string
  scope: Record<string, string>
  text: string | null
  row?: Record<string, string> | null
  ocr?: boolean
}

export interface Disagreement {
  conflict_id: string
  conflict_ids: string[]
  subject: string
  type: string
  severity: string
  explanation: string
  sides: DisagreementSide[]
}

export interface ChainStep {
  clause_id: string | null
  doc_id: string | null
  doc_name: string | null
  valid_from: string | null
  valid_to: string | null
  action: 'original' | 'substituted' | 'inserted' | 'deleted'
  span_id: string | null
  text: string | null
  source?: Source | null
}

export interface Chain {
  version_key: string
  label?: string
  steps: ChainStep[]
  in_force_step: number
  current?: { clause_id: string; text: string; doc_name: string } | null
}

export interface Calculation {
  kind: string
  formula?: string
  inputs: { name: string; value: number; span_id?: string; source?: string }[]
  steps: string[]
  result: number | null
  unit?: string
}

export interface Answer {
  status: AnswerStatus
  question: string
  as_of_date: string
  intent: string
  claims: Claim[]
  blocked_claims: Claim[]
  disagreements: Disagreement[]
  missing_evidence: string[]
  chains: Chain[]
  calculation: Calculation | null
  faithfulness_pct: number | null
  drafted: number
  passed: number
  sources: Record<string, Source>
  citations: string[]
}

export interface Message {
  msg_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  answer: Answer | null
}

export interface Doc {
  doc_id: string
  name: string
  sub: string
  type: string | null
  ref_no: string | null
  issued: string | null
  effective: string | null
  pages: number | null
  ocr: boolean
  clauses: number
  facts: number
  status: string
  status_label: string
  busy: boolean
  detail: string | null
  needs_ocr: boolean
}

export interface OutlineClause {
  clause_id: string
  label: string
  page: number
  text: string
  status: ClauseStatus
  replaced_by: string | null
}

export interface Health {
  state: 'ready' | 'warming' | 'offline'
  label: string
}

export interface Example {
  title: string
  question: string
  hint: string
}

export interface StageEvent {
  step: number
  total: number
  key: string
  label: string
}

export interface AskResult {
  user: Message
  assistant: Message
  chat: Chat
}

export interface ConflictsResponse {
  as_of: string
  cards: Disagreement[]
}

export interface AmendmentsResponse {
  as_of: string
  timelines: Chain[]
  unresolved: { doc_id: string; action: string; target: string }[]
}
