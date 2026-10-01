<script setup lang="ts">
import { computed } from 'vue'

import { useUserStore } from '@/store/user'

const store = useUserStore()

const permissionCount = computed(() => store.user?.permissions.length ?? 0)
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">数据总览</h2>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="当前用户">{{ store.displayName }}</el-descriptions-item>
      <el-descriptions-item label="登录名">{{ store.user?.username ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="岗位或部门">{{ store.user?.department ?? '-' }}</el-descriptions-item>
      <el-descriptions-item label="角色">{{ store.roles.join('、') || '-' }}</el-descriptions-item>
      <el-descriptions-item label="权限点数量">{{ permissionCount }}</el-descriptions-item>
      <el-descriptions-item label="当前阶段">阶段 2　认证与前端骨架</el-descriptions-item>
    </el-descriptions>

    <el-alert
      class="dashboard-note"
      type="info"
      :closable="false"
      show-icon
      title="本页用于验证登录链路：能显示以上信息，说明令牌注入、权限加载与前端框架都已接通。"
    />
  </div>
</template>

<style scoped>
.dashboard-note {
  margin-top: 18px;
}
</style>
