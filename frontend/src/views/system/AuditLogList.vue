<script setup>
import { onMounted, reactive, ref } from 'vue';
import { listAuditLogs } from '@/api/system';
import { usePagedList } from '@/composables/usePagedList';
const filters = reactive({ action: '', object_type: '', range: null });
const query = reactive({ action: '', object_type: '', start: '', end: '' });
const { items, total, loading, page, pageSize, load, search, changePage, changeSize } = usePagedList(query, listAuditLogs);
const detailVisible = ref(false);
const currentDetail = ref('');
onMounted(load);
async function applyFilters() {
    query.action = filters.action;
    query.object_type = filters.object_type;
    query.start = filters.range?.[0] ?? '';
    query.end = filters.range?.[1] ?? '';
    await search();
}
async function reset() {
    filters.action = '';
    filters.object_type = '';
    filters.range = null;
    await applyFilters();
}
function showDetail(row) {
    currentDetail.value = row.detail ?? '无详情';
    detailVisible.value = true;
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">审计日志</h2>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="动作">
        <el-input
          v-model="filters.action"
          placeholder="如 equipment 或 login"
          clearable
          @keyup.enter="applyFilters"
        />
      </el-form-item>
      <el-form-item label="对象类型">
        <el-input v-model="filters.object_type" placeholder="如 equipment" clearable style="width: 150px" />
      </el-form-item>
      <el-form-item label="时间范围">
        <el-date-picker
          v-model="filters.range"
          type="datetimerange"
          value-format="YYYY-MM-DD HH:mm:ss"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="applyFilters">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </el-form-item>
    </el-form>

    <el-alert
      class="audit-note"
      type="info"
      :closable="false"
      show-icon
      title="审计日志只提供查询，不能修改与删除；登录成功与失败同样留痕。"
    />

    <el-table v-loading="loading" :data="items" border stripe>
      <el-table-column prop="created_at" label="时间" width="170" />
      <el-table-column prop="username" label="操作人" width="110" />
      <el-table-column prop="action" label="动作" min-width="220" show-overflow-tooltip />
      <el-table-column label="对象" width="150">
        <template #default="{ row }">
          <span v-if="row.object_type" class="mono">
            {{ row.object_type }}{{ row.object_id ? '#' + row.object_id : '' }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="client_ip" label="来源 IP" width="130" />
      <el-table-column label="详情" width="90" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="showDetail(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @current-change="changePage"
      @size-change="changeSize"
    />

    <el-dialog v-model="detailVisible" title="审计详情" width="560px">
      <pre class="audit-detail">{{ currentDetail }}</pre>
    </el-dialog>
  </div>
</template>

<style scoped>
.filter-bar {
  margin-bottom: 4px;
}

.audit-note {
  margin-bottom: 12px;
}

.pager {
  margin-top: 14px;
  justify-content: flex-end;
}

.audit-detail {
  margin: 0;
  padding: 12px;
  background: var(--color-bg);
  border-radius: 4px;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
