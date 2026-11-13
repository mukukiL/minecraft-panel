<script setup lang="ts">
import { ref } from 'vue'
import { explain, logout, session } from './session'

const error = ref('')
const pending = ref(false)
async function signOut() {
  pending.value = true
  error.value = ''
  try { await logout() } catch (err) { error.value = explain(err) }
  finally { pending.value = false }
}
</script>

<template>
  <header v-if="session" class="topbar">
    <div class="nav">
      <RouterLink class="brand" to="/"><span class="mark" aria-hidden="true">MC</span>Minecraft Panel</RouterLink>
      <nav aria-label="管理导航">
        <RouterLink to="/">仪表盘</RouterLink>
        <RouterLink v-if="session.user.scopes.includes('users.admin')" to="/users">用户管理</RouterLink>
        <RouterLink to="/account">账户</RouterLink>
      </nav>
      <div class="identity">
        <span>{{ session.user.username }} <small>{{ session.user.role }}</small></span>
        <button class="secondary" :disabled="pending" @click="signOut">退出</button>
      </div>
    </div>
  </header>
  <p v-if="error && session" class="notice shell" role="alert">{{ error }}</p>
  <RouterView />
</template>
