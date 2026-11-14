<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from './session'
import { Box, Eye, EyeOff, LogIn } from '@lucide/vue'
import { customBranding, portrait } from './branding'

const router = useRouter()
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const busy = ref(false)
const error = ref('')
async function submit() {
  busy.value = true
  error.value = ''
  try {
    await login(username.value, password.value)
    await router.replace('/manage')
  } catch {
    error.value = '登录失败，请检查凭据或稍后再试。'
  } finally {
    password.value = ''
    showPassword.value = false
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <div class="login-frame">
      <div class="login-side">
        <div v-if="customBranding" class="portrait-frame">
          <img :src="portrait" alt="" width="640" height="640" fetchpriority="high">
        </div>
        <span v-else class="login-emblem"><Box :size="52" /></span>
        <p>Minecraft Panel</p>
      </div>
      <form class="login-form" @submit.prevent="submit">
        <h1>登录管理面板</h1>
        <label>用户名<input v-model.trim="username" name="username" autocomplete="username" maxlength="32" required></label>
        <div class="password-field">
          <label for="login-password">密码</label>
          <div class="password-input">
            <input id="login-password" v-model="password" name="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" maxlength="128" required>
            <button class="password-toggle secondary" type="button" @click="showPassword = !showPassword">
              <component :is="showPassword ? EyeOff : Eye" :size="16" aria-hidden="true" />
              {{ showPassword ? '隐藏' : '显示' }}
            </button>
          </div>
        </div>
        <Transition name="reveal">
          <p v-if="error" class="notice" role="alert">{{ error }}</p>
        </Transition>
        <button :disabled="busy"><LogIn :size="17" /> {{ busy ? '正在登录…' : '登录' }}</button>
      </form>
    </div>
  </main>
</template>
