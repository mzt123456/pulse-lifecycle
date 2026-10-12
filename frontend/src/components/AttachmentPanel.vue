<script setup>
import { ElMessage } from 'element-plus';
import { onMounted, ref, watch } from 'vue';
import { downloadAttachment, listAttachments, uploadAttachment, } from '@/api/system';
import { useUserStore } from '@/store/user';
// 运行期 props：附件挂在哪个业务对象上
const props = defineProps({
    objectType: { type: String, required: true },
    objectId: { type: Number, required: true },
});
const store = useUserStore();
const items = ref([]);
const loading = ref(false);
const uploading = ref(false);
async function load() {
    loading.value = true;
    try {
        const data = await listAttachments({
            object_type: props.objectType,
            object_id: props.objectId,
            page: 1,
            page_size: 100,
        });
        items.value = data.items;
    }
    finally {
        loading.value = false;
    }
}
onMounted(load);
watch(() => props.objectId, load);
async function handleUpload(file) {
    uploading.value = true;
    try {
        await uploadAttachment(file, props.objectType, props.objectId);
        ElMessage.success('附件已上传');
        await load();
    }
    catch (error) {
        console.warn('上传附件失败', error);
    }
    finally {
        uploading.value = false;
    }
    return false; // 已用自定义请求提交，阻止组件自身的上传行为
}
async function handleDownload(item) {
    try {
        await downloadAttachment(item.id, item.file_name);
    }
    catch (error) {
        console.warn('下载附件失败', error);
    }
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
  <div class="attachment-panel">
    <div class="attachment-header">
      <span class="attachment-title">附件</span>
      <el-upload
        v-if="store.has('attachments.upload')"
        :show-file-list="false"
        :before-upload="handleUpload"
        accept=".pdf,.jpg,.jpeg,.png,.xlsx,.xls,.docx,.txt"
      >
        <el-button size="small" type="primary" :loading="uploading">上传附件</el-button>
      </el-upload>
      <span class="attachment-hint">支持 pdf、图片、Office 文档与文本，单个不超过 50 MB</span>
    </div>

    <el-table v-loading="loading" :data="items" size="small" border>
      <el-table-column prop="file_name" label="文件名" min-width="220" show-overflow-tooltip />
      <el-table-column label="大小" width="100" align="right">
        <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
      </el-table-column>
      <el-table-column prop="uploaded_at" label="上传时间" width="170" />
      <el-table-column label="操作" width="90" align="center">
        <template #default="{ row }">
          <el-button
            v-if="store.has('attachments.download')"
            link
            type="primary"
            @click="handleDownload(row)"
          >
            下载
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <p v-if="!items.length && !loading" class="attachment-empty">暂无附件</p>
  </div>
</template>

<style scoped>
.attachment-panel {
  margin-top: 16px;
}

.attachment-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.attachment-title {
  font-size: 15px;
  font-weight: 600;
}

.attachment-hint {
  color: var(--color-muted);
  font-size: 12px;
}

.attachment-empty {
  margin: 8px 0 0;
  color: var(--color-muted);
  font-size: 13px;
}
</style>
