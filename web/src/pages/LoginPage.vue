<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../features/auth/authStore'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const errorMessage = ref('')
const submitting = ref(false)

async function submit() {
  if (!username.value.trim() || !password.value) {
    errorMessage.value = '请输入用户名和密码'
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录失败，请重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <img class="login-logo" src="/logo.png" alt="猫影" />
      <h1>登录</h1>
      <p class="login-subtitle">登录后继续使用猫影短剧</p>
      <label class="login-field">
        <span>用户名</span>
        <input v-model="username" type="text" autocomplete="username" placeholder="请输入用户名" />
      </label>
      <label class="login-field">
        <span>密码</span>
        <input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" />
      </label>
      <p v-if="errorMessage" class="login-error" role="alert">{{ errorMessage }}</p>
      <button class="login-submit" type="submit" :disabled="submitting">
        {{ submitting ? '登录中…' : '登 录' }}
      </button>
    </form>
  </main>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(1200px 600px at 20% -10%, var(--app-accent-soft, rgba(91, 92, 246, 0.14)), transparent 60%),
    var(--app-canvas, #f8f9fc);
}
.login-card {
  width: 100%;
  max-width: 380px;
  background: var(--app-surface, #fff);
  border: 1px solid var(--app-border, #e3e5ec);
  border-radius: 16px;
  padding: 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.08);
}
.login-logo {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  align-self: center;
}
.login-card h1 {
  margin: 0;
  font-size: 20px;
  text-align: center;
  color: var(--app-text, #303442);
}
.login-subtitle {
  margin: -6px 0 6px;
  text-align: center;
  font-size: 13px;
  color: var(--app-text-muted, #9398a8);
}
.login-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--app-text-muted, #9398a8);
}
.login-field input {
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--app-border, #e3e5ec);
  border-radius: 10px;
  background: var(--app-canvas, #f8f9fc);
  color: var(--app-text, #303442);
  font-size: 14px;
  outline: none;
}
.login-field input:focus {
  border-color: var(--app-accent, #5b5cf6);
  box-shadow: 0 0 0 3px var(--app-accent-soft, rgba(91, 92, 246, 0.14));
}
.login-error {
  margin: 0;
  font-size: 13px;
  color: var(--app-danger, #dc2626);
}
.login-submit {
  margin-top: 6px;
  height: 42px;
  border: none;
  border-radius: 10px;
  background: var(--app-accent, #5b5cf6);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}
.login-submit:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
