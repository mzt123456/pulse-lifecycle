/** 智能运维助手接口：故障诊断（RAG）与数据问答（Agent 工具调用）。 */

import { request } from '@/api/request'

export interface DiagnosisMatch {
  alias: string
  doc_id: string
  source: string
  source_label: string
  title: string
  score: number
  matched_terms: string[]
  record_id: number | null
  equipment_no: string | null
  fault_type: string | null
  cause: string | null
  solution: string | null
}

export interface DiagnosisItem {
  text: string
  case_ids: string[]
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface DiagnosisResult {
  found: boolean
  degraded: boolean
  reason: string | null
  causes: DiagnosisItem[]
  actions: DiagnosisItem[]
  confidence: string | null
  note: string | null
  citations: string[]
  matches: DiagnosisMatch[]
  model: string | null
  elapsed_ms: number
  filter_relaxed: boolean
  usage: TokenUsage | null
}

export interface AskStep {
  step: number
  tool: string
  arguments: Record<string, unknown>
  ok: boolean
  summary: string
  elapsed_ms: number
}

export interface AskResult {
  answer: string | null
  skill: string | null
  steps: AskStep[]
  used_tools: string[]
  degraded: boolean
  reason: string | null
  model: string | null
  elapsed_ms: number
  context_chars: {
    system_prompt: number
    skill_index: number
    all_skills_full: number
  }
}

export interface CorpusStats {
  total: number
  include_synthetic: boolean
  by_source: { source: string; source_label: string; count: number }[]
}

export interface DiagnosisPayload {
  description: string
  equipment_id?: number
  fault_type?: string
  instrument_type?: string
  top_k?: number
}

/** 诊断与问答都要等模型，默认 15 秒不够用，这里单独放宽。 */
const AI_TIMEOUT_MS = 90000

export function diagnoseFault(payload: DiagnosisPayload): Promise<DiagnosisResult> {
  return request<DiagnosisResult>({
    url: '/ai/diagnosis',
    method: 'post',
    data: payload,
    timeout: AI_TIMEOUT_MS,
  })
}

export function askQuestion(payload: { question: string; max_steps?: number }): Promise<AskResult> {
  return request<AskResult>({
    url: '/ai/ask',
    method: 'post',
    data: payload,
    timeout: AI_TIMEOUT_MS,
  })
}

export function getCorpusStats(): Promise<CorpusStats> {
  return request<CorpusStats>({ url: '/ai/corpus/stats', method: 'get' })
}
