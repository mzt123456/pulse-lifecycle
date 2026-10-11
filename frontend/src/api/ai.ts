/** 智能运维助手接口：故障诊断（RAG）与数据问答（Agent 工具调用）。 */

import { request } from '@/api/request'

export interface DiagnosisMatch {
  alias: string
  doc_id: string
  source: string
  source_label: string
  title: string
  /** 融合分：关键词与向量两路归一化加权后的匹配度（0-1） */
  score: number
  /** 相关性重排打分（0-10），未执行重排时为空 */
  rerank_score: number | null
  /** 重排给出的理由 */
  rerank_reason: string | null
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

export interface RetrievalInfo {
  /** hybrid 表示向量与关键词融合，bm25 表示只用关键词 */
  mode: string
  bm25_candidates: number
  vector_candidates: number
  /** 向量通道不可用时的原因 */
  note: string | null
}

export interface RerankInfo {
  applied: boolean
  kept: number
  dropped: number
  degraded: boolean
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
  retrieval: RetrievalInfo
  rerank: RerankInfo
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
  /** 服务端发放的会话 ID，追问时带回去即可续上短期记忆 */
  conversation_id: string | null
  /** 本次历史来自服务端记忆（server）、随请求带来（client）还是无历史（none） */
  memory_source: 'server' | 'client' | 'none'
  context_chars: {
    system_prompt: number
    skill_index: number
    all_skills_full: number
    history: number
  }
  history_turns: number
}

export interface AskTurn {
  question: string
  answer: string | null
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

export function askQuestion(payload: {
  question: string
  max_steps?: number
  /** 会话 ID：带上它就用服务端的短期记忆续接 */
  conversation_id?: string
  /** 最近几轮问答：服务端没有该会话时（例如刚重启）作为兜底 */
  history?: AskTurn[]
}): Promise<AskResult> {
  return request<AskResult>({
    url: '/ai/ask',
    method: 'post',
    data: payload,
    timeout: AI_TIMEOUT_MS,
  })
}

/** 忘掉服务端的会话记忆；不存在时也返回成功（幂等）。 */
export function forgetConversation(conversationId: string): Promise<{
  conversation_id: string
  removed: boolean
}> {
  return request({ url: `/ai/conversations/${conversationId}`, method: 'delete' })
}

export function getCorpusStats(): Promise<CorpusStats> {
  return request<CorpusStats>({ url: '/ai/corpus/stats', method: 'get' })
}
