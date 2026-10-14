<script setup>
import { computed } from 'vue';
import { usePreferencesStore } from '@/store/preferences';
// 运行期 props：列定义、数据与加载状态；stripe 默认开启，保持与原实现一致的观感
const props = defineProps({
    tableKey: { type: String, required: true },
    columns: { type: Array, required: true },
    data: { type: Array, required: true },
    loading: { type: Boolean, default: false },
    stripe: { type: Boolean, default: true },
});
const store = usePreferencesStore();
const allKeys = computed(() => props.columns.map((column) => column.key));
const defaultKeys = computed(() => props.columns.filter((column) => !column.defaultHidden).map((column) => column.key));
const order = computed(() => store.columnsFor(props.tableKey, defaultKeys.value, allKeys.value));
const visibleColumns = computed(() => order.value
    .map((key) => props.columns.find((column) => column.key === key))
    .filter((column) => Boolean(column)));
const hiddenColumns = computed(() => props.columns.filter((column) => !order.value.includes(column.key)));
async function toggleColumn(key, checked) {
    const next = checked
        ? [...order.value, key]
        : order.value.filter((item) => item !== key);
    await store.setColumns(props.tableKey, next);
}
async function moveColumn(key, delta) {
    const next = [...order.value];
    const index = next.indexOf(key);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= next.length) {
        return;
    }
    ;
    [next[index], next[target]] = [next[target], next[index]];
    await store.setColumns(props.tableKey, next);
}
async function resetColumns() {
    await store.setColumns(props.tableKey, defaultKeys.value);
}
</script>

<template>
  <div class="data-table">
    <div class="table-toolbar">
      <div class="toolbar-left">
        <slot name="toolbar" />
      </div>
      <el-popover placement="bottom-end" :width="280" trigger="click">
        <template #reference>
          <el-button size="small">列设置</el-button>
        </template>
        <div class="column-setting">
          <p class="column-hint">勾选要显示的列，用上移 / 下移调整顺序；设置随账号保存。</p>
          <div v-for="column in visibleColumns" :key="column.key" class="column-row">
            <el-checkbox :model-value="true" @change="(value: boolean) => toggleColumn(column.key, value)">
              {{ column.label }}
            </el-checkbox>
            <span v-if="!column.fixed" class="column-actions">
              <el-button link :disabled="order.indexOf(column.key) === 0" @click="moveColumn(column.key, -1)">
                上移
              </el-button>
              <el-button
                link
                :disabled="order.indexOf(column.key) === order.length - 1"
                @click="moveColumn(column.key, 1)"
              >
                下移
              </el-button>
            </span>
            <span v-else class="column-fixed-hint">固定在右侧</span>
          </div>
          <div v-for="column in hiddenColumns" :key="column.key" class="column-row">
            <el-checkbox :model-value="false" @change="(value: boolean) => toggleColumn(column.key, value)">
              {{ column.label }}
            </el-checkbox>
          </div>
          <el-button link type="primary" @click="resetColumns">恢复默认</el-button>
        </div>
      </el-popover>
    </div>

    <el-table v-loading="loading" :data="data" border :stripe="stripe">
      <el-table-column
        v-for="column in visibleColumns"
        :key="column.key"
        :prop="column.key"
        :label="column.label"
        :width="column.width"
        :min-width="column.minWidth"
        :align="column.align"
        :fixed="column.fixed"
        :show-overflow-tooltip="column.tooltip"
      >
        <template #default="scope">
          <slot :name="`cell-${column.key}`" v-bind="scope">
            {{ scope.row[column.key] ?? '-' }}
          </slot>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.toolbar-left {
  display: flex;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.column-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--color-muted);
}

.column-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.column-actions {
  display: flex;
  gap: 4px;
}

.column-fixed-hint {
  font-size: 12px;
  color: var(--color-muted);
}

.column-actions :deep(.el-button) {
  padding: 0 2px;
  font-size: 12px;
}
</style>
