<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import {
  askQuestion,
  diagnoseFault,
  getCorpusStats,
  type AskTurn,
  type AskResult,
  type CorpusStats,
  type DiagnosisResult,
} from '@/api/ai'
import { getDictItems } from '@/api/dict'
import { listEquipment } from '@/api/equipment'
import MarkdownText from '@/components/MarkdownText.vue'
import { useUserStore } from '@/store/user'
import type { Equipment } from '@/types'

type Mode = 'diagnosis' | 'ask'

interface AssistantEntry {
  id: number
  mode: Mode
  question: string
  askedAt: string
  diagnosis?: DiagnosisResult
  ask?: AskResult
  error?: string
}

const store = useUserStore()
const canDiagnose = computed(() => store.has('fault.view'))
const canSeeCorpus = computed(() => store.has('system.settings'))

const mode = ref<Mode>('ask')
const question = ref('')
const submitting = ref(false)
const entries = ref<AssistantEntry[]>([])

const equipmentId = ref<number | null>(null)
const faultType = ref('')
const instrumentType = ref('')
const equipmentOptions = ref<Equipment[]>([])
const faultTypes = ref<string[]>([])
const instrumentTypes = ref<string[]>([])
const corpus = ref<CorpusStats | null>(null)

const EXAMPLES: Record<Mode, string[]> = {
  diagnosis: [
    '下井之后地面收不到脉冲信号，仪器不上电',
    '下去之后声音不对，咔咔响，阀芯有点卡',
    '压力保不住，一直往下掉',
  ],
  ask: [
    '现在设备整体情况怎么样？有没有要注意的',
    '耗材库存还剩多少，有没有低于安全库存的',
    'PLT-DEMO-1 最近一次维保是什么时候，结果怎么样',
  ],
}

const examples = computed(() => EXAMPLES[mode.value])

/** 追问需要的历史：只取最近几轮"问答模式且有回答"的记录，按时间正序传给后端。 */
function recentHistory(): AskTurn[] {
  return entries.value
    .filter((item) => item.mode === 'ask' && item.ask?.answer)
    .slice(0, 6)
    .reverse()
    .map((item) => ({ question: item.question, answer: item.ask?.answer ?? null }))
}

function clearHistory(): void {
  entries.value = []
}

onMounted(async () => {
  if (canDiagnose.value) {
    mode.value = 'diagnosis'
  }
  try {
    const dict = await getDictItems()
    faultTypes.value = dict['故障类型'] ?? []
    instrumentTypes.value = dict['仪器类型'] ?? []
  } catch {
    // 字典加载失败不影响主流程，下拉为空即可
  }
  if (canDiagnose.value) {
    try {
      equipmentOptions.value = (await listEquipment({ page: 1, page_size: 100 })).items
    } catch {
      equipmentOptions.value = []
    }
  }
  if (canSeeCorpus.value) {
    try {
      corpus.value = await getCorpusStats()
    } catch {
      corpus.value = null
    }
  }
})

function useExample(text: string): void {
  question.value = text
}

/** 引用里存的是语料文档 ID，页面上显示成 C1、C2 这种编号，鼠标悬停看标题。 */
function citeLabel(result: DiagnosisResult, docId: string): string {
  const match = result.matches.find((item) => item.doc_id === docId)
  return match ? match.alias : docId
}

function citeTitle(result: DiagnosisResult, docId: string): string {
  const match = result.matches.find((item) => item.doc_id === docId)
  if (!match) {
    return docId
  }
  const rerank = match.rerank_score === null ? '' : `，重排 ${match.rerank_score}/10`
  return `${match.source_label}｜${match.title}（融合分 ${match.score}${rerank}）`
}

/** 检索通道的中文展示：混合、关键词，以及向量不可用时的原因。 */
function retrievalLabel(result: DiagnosisResult): string {
  const { mode, bm25_candidates: bm25, vector_candidates: vector } = result.retrieval
  return mode === 'hybrid'
    ? `混合检索（关键词 ${bm25} 条 / 向量 ${vector} 条）`
    : `关键词检索（${bm25} 条）`
}

async function submit(): Promise<void> {
  const text = question.value.trim()
  if (text.length < 4) {
    ElMessage.warning('把现象或问题描述得再具体一点（至少 4 个字）')
    return
  }

  submitting.value = true
  const entry: AssistantEntry = {
    id: Date.now(),
    mode: mode.value,
    question: text,
    askedAt: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
  }

  try {
    if (entry.mode === 'diagnosis') {
      entry.diagnosis = await diagnoseFault({
        description: text,
        equipment_id: equipmentId.value ?? undefined,
        fault_type: faultType.value || undefined,
        instrument_type: instrumentType.value || undefined,
        top_k: 5,
      })
    } else {
      entry.ask = await askQuestion({ question: text, history: recentHistory() })
    }
    question.value = ''
    entries.value.unshift(entry)
  } catch (error) {
    entry.error = error instanceof Error ? error.message : '请求失败'
    entries.value.unshift(entry)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="assistant">
    <div class="page-card assistant-bar">
      <el-radio-group v-model="mode" size="small">
        <el-radio-button v-if="canDiagnose" value="diagnosis">故障诊断</el-radio-button>
        <el-radio-button value="ask">数据问答</el-radio-button>
      </el-radio-group>
      <span class="assistant-hint">
        诊断依据案例库给结论并附引用；数据问答由模型按你的权限自动选工具取数
      </span>
      <div v-if="corpus" class="assistant-corpus">
        <el-tag v-for="item in corpus.by_source" :key="item.source" size="small" type="info">
          {{ item.source_label }} {{ item.count }} 条
        </el-tag>
        <el-tag v-if="corpus.include_synthetic" size="small" type="warning">
          含仿真案例（真实数据待迁移）
        </el-tag>
      </div>
      <el-button v-if="entries.length" link size="small" @click="clearHistory">清空会话</el-button>
    </div>

    <div class="page-card">
      <el-input
        v-model="question"
        type="textarea"
        :rows="3"
        maxlength="500"
        show-word-limit
        :placeholder="
          mode === 'diagnosis'
            ? '用现场的话描述现象，例如：下井之后地面收不到脉冲信号'
            : '问一个业务问题，例如：耗材库存还剩多少'
        "
        @keydown.ctrl.enter.prevent="submit"
      />

      <div v-if="mode === 'diagnosis'" class="assistant-filters">
        <el-select
          v-model="equipmentId"
          placeholder="关联设备（可选）"
          clearable
          filterable
          size="small"
          style="width: 190px"
        >
          <el-option
            v-for="item in equipmentOptions"
            :key="item.id"
            :label="item.equipment_no"
            :value="item.id"
          />
        </el-select>
        <el-select
          v-model="faultType"
          placeholder="故障类型（可选）"
          clearable
          size="small"
          style="width: 150px"
        >
          <el-option v-for="item in faultTypes" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select
          v-model="instrumentType"
          placeholder="仪器类型（可选）"
          clearable
          size="small"
          style="width: 150px"
        >
          <el-option v-for="item in instrumentTypes" :key="item" :label="item" :value="item" />
        </el-select>
        <el-button type="primary" size="small" :loading="submitting" @click="submit">
          开始诊断
        </el-button>
      </div>
      <div v-else class="assistant-filters">
        <el-button type="primary" size="small" :loading="submitting" @click="submit">
          提问
        </el-button>
      </div>

      <div class="assistant-examples">
        <span class="assistant-examples-label">示例</span>
        <el-button v-for="text in examples" :key="text" link size="small" @click="useExample(text)">
          {{ text }}
        </el-button>
      </div>
    </div>

    <div v-for="entry in entries" :key="entry.id" class="page-card assistant-entry">
      <div class="assistant-entry-head">
        <el-tag size="small" :type="entry.mode === 'diagnosis' ? 'primary' : 'success'">
          {{ entry.mode === 'diagnosis' ? '故障诊断' : '数据问答' }}
        </el-tag>
        <span class="assistant-question">{{ entry.question }}</span>
        <span class="assistant-time">{{ entry.askedAt }}</span>
      </div>

      <el-alert v-if="entry.error" type="error" :closable="false" :title="entry.error" />

      <!-- 故障诊断结果 -->
      <template v-if="entry.diagnosis">
        <el-alert
          v-if="entry.diagnosis.degraded"
          type="warning"
          :closable="false"
          :title="entry.diagnosis.reason || '已降级为相似案例检索'"
          class="assistant-alert"
        />
        <el-alert
          v-if="entry.diagnosis.filter_relaxed"
          type="info"
          :closable="false"
          title="按条件没有命中，已自动放宽过滤范围"
          class="assistant-alert"
        />
        <el-alert
          v-if="entry.diagnosis.retrieval.note"
          type="info"
          :closable="false"
          :title="entry.diagnosis.retrieval.note"
          class="assistant-alert"
        />
        <el-alert
          v-if="entry.diagnosis.rerank.degraded"
          type="warning"
          :closable="false"
          title="相关性重排本次未生效，候选按原顺序保留，结论请谨慎采用"
          class="assistant-alert"
        />

        <div class="assistant-meta">
          <el-tag v-if="entry.diagnosis.confidence" size="small" type="warning">
            置信度 {{ entry.diagnosis.confidence }}
          </el-tag>
          <el-tag size="small" type="info">{{ retrievalLabel(entry.diagnosis) }}</el-tag>
          <span v-if="entry.diagnosis.rerank.applied">
            重排保留 {{ entry.diagnosis.rerank.kept }} / 丢弃 {{ entry.diagnosis.rerank.dropped }}
          </span>
          <span>耗时 {{ entry.diagnosis.elapsed_ms }} ms</span>
          <span v-if="entry.diagnosis.model">模型 {{ entry.diagnosis.model }}</span>
          <span v-if="entry.diagnosis.usage">
            token {{ entry.diagnosis.usage.total_tokens }}
          </span>
        </div>

        <template v-if="entry.diagnosis.found">
          <div class="assistant-section">
            <div class="assistant-section-title">可能原因</div>
            <ul class="assistant-list">
              <li v-for="(item, index) in entry.diagnosis.causes" :key="index">
                {{ item.text }}
                <el-tooltip
                  v-for="docId in item.case_ids"
                  :key="docId"
                  :content="citeTitle(entry.diagnosis, docId)"
                  placement="top"
                >
                  <span class="assistant-cite">{{ citeLabel(entry.diagnosis, docId) }}</span>
                </el-tooltip>
              </li>
            </ul>
          </div>

          <div v-if="entry.diagnosis.actions.length" class="assistant-section">
            <div class="assistant-section-title">建议处置</div>
            <ul class="assistant-list">
              <li v-for="(item, index) in entry.diagnosis.actions" :key="index">
                {{ item.text }}
                <el-tooltip
                  v-for="docId in item.case_ids"
                  :key="docId"
                  :content="citeTitle(entry.diagnosis, docId)"
                  placement="top"
                >
                  <span class="assistant-cite">{{ citeLabel(entry.diagnosis, docId) }}</span>
                </el-tooltip>
              </li>
            </ul>
          </div>

          <div v-if="entry.diagnosis.note" class="assistant-note">{{ entry.diagnosis.note }}</div>
        </template>
        <div v-else class="assistant-empty">
          知识库里没有与这段描述相似的案例{{ entry.diagnosis.reason ? `（${entry.diagnosis.reason}）` : '' }}，
          因此没有给出原因推测。
        </div>

        <el-collapse v-if="entry.diagnosis.matches.length" class="assistant-collapse">
          <el-collapse-item :title="`检索到的相似案例（${entry.diagnosis.matches.length} 条）`">
            <el-table :data="entry.diagnosis.matches" size="small" border>
              <el-table-column prop="alias" label="编号" width="70" align="center" />
              <el-table-column prop="source_label" label="来源" width="110" />
              <el-table-column prop="title" label="案例" min-width="220" show-overflow-tooltip />
              <el-table-column prop="score" label="融合分" width="90" align="right" />
              <el-table-column label="重排分" width="90" align="right">
                <template #default="{ row }">
                  <el-tooltip v-if="row.rerank_score !== null" :content="row.rerank_reason || '重排未给出理由'" placement="top">
                    <span>{{ row.rerank_score }}/10</span>
                  </el-tooltip>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column label="命中词" min-width="140">
                <template #default="{ row }">
                  {{ row.matched_terms.length ? row.matched_terms.join('、') : '（向量命中）' }}
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </template>

      <!-- 数据问答结果 -->
      <template v-if="entry.ask">
        <el-alert
          v-if="entry.ask.degraded"
          type="warning"
          :closable="false"
          :title="entry.ask.reason || '本次回答已降级'"
          class="assistant-alert"
        />

        <div class="assistant-meta">
          <el-tag v-if="entry.ask.skill" size="small">技能 {{ entry.ask.skill }}</el-tag>
          <span>耗时 {{ entry.ask.elapsed_ms }} ms</span>
          <span v-if="entry.ask.model">模型 {{ entry.ask.model }}</span>
          <span v-if="entry.ask.history_turns">带入 {{ entry.ask.history_turns }} 轮历史</span>
          <el-tooltip
            :content="`技能索引常驻 ${entry.ask.context_chars.skill_index} 字；若把全部技能正文与参考资料一次装入，需要 ${entry.ask.context_chars.all_skills_full} 字；本次历史问答占用 ${entry.ask.context_chars.history} 字`"
            placement="top"
          >
            <span>上下文 {{ entry.ask.context_chars.system_prompt }} 字</span>
          </el-tooltip>
        </div>

        <div v-if="entry.ask.answer" class="assistant-answer">
          <MarkdownText :text="entry.ask.answer" />
        </div>
        <div v-else class="assistant-empty">本次没有生成回答，请根据下方工具调用结果判断。</div>

        <el-collapse v-if="entry.ask.steps.length" class="assistant-collapse">
          <el-collapse-item :title="`工具调用（${entry.ask.steps.length} 次：${entry.ask.used_tools.join('、')}）`">
            <el-timeline>
              <el-timeline-item
                v-for="(step, index) in entry.ask.steps"
                :key="index"
                :type="step.ok ? 'primary' : 'warning'"
                :timestamp="`${step.elapsed_ms} ms`"
              >
                <span class="mono assistant-tool">{{ step.tool }}</span>
                <span class="assistant-tool-args">{{ JSON.stringify(step.arguments) }}</span>
                <div class="assistant-tool-summary">{{ step.summary }}</div>
              </el-timeline-item>
            </el-timeline>
          </el-collapse-item>
        </el-collapse>
      </template>
    </div>
  </div>
</template>

<style scoped>
.assistant-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.assistant-hint {
  font-size: 12px;
  color: #7f8c8d;
}

.assistant-corpus {
  margin-left: auto;
  display: flex;
  gap: 6px;
}

.assistant-bar + .page-card {
  margin-bottom: 14px;
}

.assistant-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.assistant-examples {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.assistant-examples-label {
  font-size: 12px;
  color: #95a5a6;
}

.assistant-entry {
  margin-bottom: 14px;
}

.assistant-entry-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.assistant-question {
  font-weight: 600;
}

.assistant-time {
  margin-left: auto;
  font-size: 12px;
  color: #95a5a6;
}

.assistant-alert {
  margin-bottom: 10px;
}

.assistant-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  font-size: 12px;
  color: #7f8c8d;
}

.assistant-section {
  margin-bottom: 12px;
}

.assistant-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #000;
  margin-bottom: 6px;
}

.assistant-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
}

.assistant-cite {
  margin-left: 6px;
  padding: 0 6px;
  font-size: 12px;
  color: var(--color-accent);
  background: #eaf3fa;
  border-radius: 3px;
  cursor: help;
}

.assistant-note {
  padding: 8px 12px;
  font-size: 13px;
  color: #7f8c8d;
  background: #f7f9fa;
  border-left: 3px solid var(--color-muted);
}

.assistant-answer {
  padding: 12px 14px;
  background: #f7f9fa;
  border-left: 3px solid var(--color-accent);
}

.assistant-empty {
  padding: 12px 14px;
  color: #7f8c8d;
  background: #f7f9fa;
}

.assistant-collapse {
  margin-top: 12px;
}

.assistant-tool {
  font-weight: 600;
}

.assistant-tool-args {
  margin-left: 8px;
  font-size: 12px;
  color: #95a5a6;
}

.assistant-tool-summary {
  font-size: 12px;
  color: #7f8c8d;
}
</style>
