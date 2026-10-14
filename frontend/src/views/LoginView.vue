<script setup>
import { ElMessage } from 'element-plus';
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useUserStore } from '@/store/user';
const router = useRouter();
const route = useRoute();
const store = useUserStore();
const formRef = ref();
const loading = ref(false);
const form = reactive({ username: '', password: '' });
const rules = {
    username: [{ required: true, message: '请输入登录名', trigger: 'blur' }],
    password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
};
async function submit() {
    if (!formRef.value) {
        return;
    }
    const valid = await formRef.value.validate().catch(() => false);
    if (!valid) {
        return;
    }
    loading.value = true;
    try {
        await store.login(form.username, form.password);
        ElMessage.success('登录成功');
        const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard';
        await router.replace(redirect);
    }
    catch (error) {
        // 失败提示已由请求封装统一弹出，这里只保留一行日志便于排查
        console.warn('登录失败', error);
    }
    finally {
        loading.value = false;
    }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">剪切阀脉冲器全生命周期管理系统</h1>
      <p class="login-subtitle">设备全生命周期管理 · 演示环境</p>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="登录名" prop="username">
          <el-input v-model="form.username" placeholder="请输入登录名" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            show-password
            autocomplete="current-password"
          />
        </el-form-item>
        <el-button type="primary" :loading="loading" class="login-button" @click="submit">
          登录
        </el-button>
      </el-form>

      <p class="login-hint">忘记密码请联系系统管理员重置</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--color-primary);
}

.login-card {
  width: 380px;
  padding: 32px 32px 24px;
  background: var(--color-surface);
  border-radius: 6px;
  box-shadow: 0 8px 24px rgb(0 0 0 / 18%);
}

.login-title {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  color: #000;
  text-align: center;
}

.login-subtitle {
  margin: 6px 0 22px;
  font-size: 13px;
  color: var(--color-text-secondary);
  text-align: center;
}

.login-button {
  width: 100%;
  height: 38px;
  font-size: 15px;
}

.login-hint {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--color-muted);
  text-align: center;
}
</style>
