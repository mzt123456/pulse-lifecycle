<script setup>
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, reactive, ref } from 'vue';
import { createKnowledgeText, deleteKnowledgeDocument, getKnowledgeDocument, getKnowledgeStats, listKnowledgeDocuments, uploadKnowledgeDocument, } from '@/api/knowledge';
import DataTable from '@/components/DataTable.vue';
import { usePagedList } from '@/composables/usePagedList';
import { usePreferencesStore } from '@/store/preferences';
import { useUserStore } from '@/store/user';
const store = useUserStore();
const preferences = usePreferencesStore();
const columns = [
    { key: 'title', label: '标题', minWidth: 200, tooltip: true },
    { key: 'source_type', label: '来源', width: 90, align: 'center' },
    { key: 'file_name', label: '文件名', minWidth: 160, tooltip: true },
    { key: 'chunk_count', label: '分块数', width: 90, align: 'right' },
    { key: 'char_count', label: '字数', width: 90, align: 'right' },
    { key: 'status', label: '解析状态', width: 110, align: 'center' },
    { key: 'created_by_name', label: '录入人', width: 110 },
    { key: 'created_at', label: '录入时间', width: 170 },
    { key: 'actions', label: '操作', width: 130, fixed: 'right', align: 'center' },
];
const filters = reactive({ status: undefined });
const query = reactive({ keyword: '', status: '' });
const keyword = ref('');
const { items, total, loading, page, pageSize, load, search, changePage, changeSize } = usePagedList(query, listKnowledgeDocuments);
const stats = ref({ documents: 0, chunks: 0, failed: 0, characters: 0 });
const detailVisible = ref(false);
const detail = ref(null);
const detailLoading = ref(false);
const pasteVisible = ref(false);
const submitting = ref(false);
const uploading = ref(false);
const pasteForm = reactive({ title: '', content: '' });
function changePageSize(size) {
    void preferences.setPageSize(size);
    void changeSize(size);
}
async function loadStats() {
    stats.value = await getKnowledgeStats();
}
async function refresh() {
    await Promise.all([load(), loadStats()]);
}
async function applyFilters() {
    query.keyword = keyword.value.trim();
    query.status = filters.status ?? '';
    await search();
}
async function resetFilters() {
    keyword.value = '';
    filters.status = undefined;
    await applyFilters();
}
onMounted(async () => {
    await preferences.load();
    pageSize.value = preferences.pageSize;
    await refresh();
});
async function showDetail(row) {
    detailVisible.value = true;
    detailLoading.value = true;
    detail.value = null;
    try {
        detail.value = await getKnowledgeDocument(row.id);
    }
    finally {
        detailLoading.value = false;
    }
}
async function handleUpload(file) {
    uploading.value = true;
    try {
        const document = await uploadKnowledgeDocument(file);
        if (document.status === 'failed') {
            // 解析失败也入库了，把原因直接告诉用户，避免以为上传成功
            ElMessage.warning(`已记录但未解析成功：${document.error ?? '未提取到正文'}`);
        }
        else {
            ElMessage.success(`已入库，切成 ${document.chunk_count} 个分块`);
        }
        await refresh();
    }
    catch (error) {
        console.warn('上传知识库文档失败', error);
    }
    finally {
        uploading.value = false;
    }
    return false; // 已用自定义请求提交，阻止 el-upload 自身行为
}
function openPaste() {
    pasteForm.title = '';
    pasteForm.content = '';
    pasteVisible.value = true;
}
async function submitPaste() {
    if (!pasteForm.title.trim() || !pasteForm.content.trim()) {
        ElMessage.warning('标题与正文都不能为空');
        return;
    }
    submitting.value = true;
    try {
        const document = await createKnowledgeText({
            title: pasteForm.title.trim(),
            content: pasteForm.content,
        });
        ElMessage.success(`已入库，切成 ${document.chunk_count} 个分块`);
        pasteVisible.value = false;
        await refresh();
    }
    catch (error) {
        console.warn('粘贴文本入库失败', error);
    }
    finally {
        submitting.value = false;
    }
}
async function handleDelete(row) {
    try {
        await ElMessageBox.confirm(`确定删除《${row.title}》吗？删除后该文档不再参与检索，记录会保留在审计日志里。`, '删除知识库文档', { type: 'warning' });
    }
    catch {
        return;
    }
    await deleteKnowledgeDocument(row.id);
    ElMessage.success('已删除');
    await refresh();
}
function formatSize(size) {
    if (!size) {
        return '-';
    }
    return size < 1024 * 1024
        ? `${(size / 1024).toFixed(1)} KB`
        : `${(size / 1024 / 1024).toFixed(1)} MB`;
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">知识库</h2>

    <el-row :gutter="12" class="stat-row">
      <el-col :span="6">
        <div class="stat-card">
          <span class="stat-label">文档数</span>
          <span class="stat-value">{{ stats.documents }}</span>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <span class="stat-label">分块数</span>
          <span class="stat-value">{{ stats.chunks }}</span>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <span class="stat-label">解析失败</span>
          <span class="stat-value" :class="{ 'stat-danger': stats.failed > 0 }">
            {{ stats.failed }}
          </span>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <span class="stat-label">正文字数</span>
          <span class="stat-value">{{ stats.characters }}</span>
        </div>
      </el-col>
    </el-row>

    <el-alert
      class="knowledge-note"
      type="info"
      :closable="false"
      show-icon
      title="上传或粘贴的文档会按段落切块后进入检索语料：故障诊断时会连同历史故障记录一起被召回并引用。支持 txt / md / docx / pdf（扫描件无文字层，无法解析）。"
    />

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="标题">
        <el-input
          v-model="keyword"
          placeholder="按标题模糊搜索"
          clearable
          style="width: 200px"
          @keyup.enter="applyFilters"
        />
      </el-form-item>
      <el-form-item label="解析状态">
        <el-select v-model="filters.status" placeholder="全部" clearable style="width: 130px">
          <el-option label="已入库" value="ready" />
          <el-option label="解析失败" value="failed" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </el-form-item>
    </el-form>

    <DataTable table-key="knowledge_document" :columns="columns" :data="items" :loading="loading">
      <template #toolbar>
        <el-upload
          v-if="store.has('knowledge.upload')"
          :show-file-list="false"
          :before-upload="handleUpload"
          accept=".txt,.md,.docx,.pdf"
        >
          <el-button type="success" :loading="uploading">上传文档</el-button>
        </el-upload>
        <el-button v-if="store.has('knowledge.upload')" @click="openPaste">粘贴文本</el-button>
      </template>

      <template #cell-title="{ row }">
        <el-button link type="primary" @click="showDetail(row)">{{ row.title }}</el-button>
      </template>

      <template #cell-source_type="{ row }">
        <el-tag size="small" :type="row.source_type === 'file' ? 'info' : 'success'">
          {{ row.source_type === 'file' ? '文件' : '粘贴' }}
        </el-tag>
      </template>

      <template #cell-status="{ row }">
        <el-tag v-if="row.status === 'ready'" type="success" size="small">已入库</el-tag>
        <el-tooltip v-else :content="row.error ?? '解析失败'" placement="top">
          <el-tag type="danger" size="small">解析失败</el-tag>
        </el-tooltip>
      </template>

      <template #cell-created_by_name="{ row }">{{ row.created_by_name || '-' }}</template>

      <template #cell-actions="{ row }">
        <el-button link type="primary" @click="showDetail(row)">详情</el-button>
        <el-button
          v-if="store.has('knowledge.delete')"
          link
          type="danger"
          @click="handleDelete(row)"
        >
          删除
        </el-button>
      </template>
    </DataTable>

    <el-pagination
      class="pager"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @current-change="changePage"
      @size-change="changePageSize"
    />

    <el-dialog v-model="detailVisible" title="文档详情" width="720px">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detail" :column="2" border size="small">
          <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
          <el-descriptions-item label="来源">
            {{ detail.source_type === 'file' ? `文件：${detail.file_name ?? '-'}` : '页面粘贴' }}
          </el-descriptions-item>
          <el-descriptions-item label="文件大小">
            {{ formatSize(detail.size_bytes) }}
          </el-descriptions-item>
          <el-descriptions-item label="分块 / 字数">
            {{ detail.chunk_count }} 块 / {{ detail.char_count }} 字
          </el-descriptions-item>
          <el-descriptions-item label="录入人">{{ detail.created_by_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="录入时间">{{ detail.created_at }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.error" label="解析失败原因" :span="2">
            <span class="error-text">{{ detail.error }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <template v-if="detail?.chunks.length">
          <p class="chunk-hint">分块预览（最多 3 段，检索命中的就是这些块）</p>
          <div v-for="chunk in detail.chunks" :key="chunk.seq" class="chunk-item">
            <span class="chunk-seq">第 {{ chunk.seq }} 段 · {{ chunk.char_count }} 字</span>
            <p class="chunk-text">{{ chunk.text }}</p>
          </div>
        </template>
        <el-empty v-else-if="detail && !detailLoading" description="没有可预览的分块" />
      </div>
    </el-dialog>

    <el-dialog v-model="pasteVisible" title="粘贴文本入库" width="640px">
      <el-form :model="pasteForm" label-width="72px">
        <el-form-item label="标题" required>
          <el-input v-model="pasteForm.title" placeholder="如：剪切阀脉冲器扭矩标定规程" />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input
            v-model="pasteForm.content"
            type="textarea"
            :rows="12"
            placeholder="粘贴规范、操作手册或经验总结，入库后会按 500 字左右切块参与检索"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pasteVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitPaste">入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stat-row {
  margin-bottom: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 16px;
  background: var(--color-bg);
  border-radius: 4px;
}

.stat-label {
  color: var(--color-muted);
  font-size: 12px;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
}

.stat-danger {
  color: var(--el-color-danger);
}

.knowledge-note {
  margin-bottom: 12px;
}

.filter-bar {
  margin-bottom: 4px;
}

.pager {
  margin-top: 14px;
  justify-content: flex-end;
}

.chunk-hint {
  margin: 16px 0 8px;
  color: var(--color-muted);
  font-size: 12px;
}

.chunk-item {
  margin-bottom: 10px;
  padding: 10px 12px;
  background: var(--color-bg);
  border-radius: 4px;
}

.chunk-seq {
  color: var(--color-muted);
  font-size: 12px;
}

.chunk-text {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}

.error-text {
  color: var(--el-color-danger);
}
</style>
