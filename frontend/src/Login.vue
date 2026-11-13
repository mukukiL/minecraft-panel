<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from './session'

const router = useRouter()
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')
async function submit() {
  busy.value = true
  error.value = ''
  try {
    await login(username.value, password.value)
    await router.replace('/')
  } catch {
    error.value = '登录失败，请检查凭据或稍后再试。'
  } finally {
    password.value = ''
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <div class="login-frame">
      <section class="login-side">
        <span class="mark" aria-hidden="true">MC</span>
        <p>Minecraft Panel</p>
      </section>
      <form class="login-form" @submit.prevent="submit">
        <h1>登录管理面板</h1>
        <label>用户名<input v-model.trim="username" name="username" autocomplete="username" maxlength="32" required></label>
        <label>密码<input v-model="password" name="password" type="password" autocomplete="current-password" maxlength="128" required></label>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
        <button :disabled="busy">{{ busy ? '正在登录…' : '登录' }}</button>
      </form>
    </div>
  </main>
</template>
