<script setup lang="ts">
import { ref } from 'vue'
import { api, explain, session } from './session'
const current = ref('')
const replacement = ref('')
const confirmation = ref('')
const error = ref('')
const busy = ref(false)
async function submit() {
  if (replacement.value !== confirmation.value) {
    error.value = '两次输入的新密码不一致。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await api('/auth/password', { method: 'POST', body: JSON.stringify({
      current_password: current.value, new_password: replacement.value,
    }) })
    session.value = null
  } catch (err) { error.value = explain(err) }
  finally { current.value = replacement.value = confirmation.value = ''; busy.value = false }
}
</script>
<template>
  <main class="shell">
    <div class="heading"><h1>账户</h1></div>
    <section class="card account">
      <h2>修改密码</h2>
      <p class="muted">修改后需要重新登录，其他设备也会退出。</p>
      <form class="stack" @submit.prevent="submit">
        <label>当前密码<input v-model="current" type="password" autocomplete="current-password" maxlength="128" required></label>
        <label>新密码<input v-model="replacement" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label>
        <label>确认新密码<input v-model="confirmation" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
        <button :disabled="busy">保存密码</button>
      </form>
    </section>
  </main>
</template>
