<script setup lang="ts">
import { ref } from 'vue'
import { Activity, Box, LayoutDashboard, LogIn, LogOut, Palette, Settings2, UsersRound } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { explain, logout, session } from './session'
import { branding } from './branding'

const router = useRouter()
const error = ref('')
const pending = ref(false)
async function signOut() {
  pending.value = true
  error.value = ''
  try { await logout(); await router.replace('/') } catch (err) { error.value = explain(err) }
  finally { pending.value = false }
}
</script>

<template>
  <div class="wallpaper" aria-hidden="true">
    <img v-if="branding.background" :src="branding.background" alt="" fetchpriority="high">
  </div>
  <header class="topbar">
    <div class="nav">
      <RouterLink class="brand" to="/">
        <img v-if="branding.portrait" class="brand-portrait" :src="branding.portrait" alt="" width="38" height="38">
        <span v-else class="brand-portrait brand-placeholder"><Box :size="20" /></span>
        <span class="brand-name">{{ branding.title }}</span>
      </RouterLink>
      <nav aria-label="主导航">
        <RouterLink to="/"><Activity :size="16" /> 状态监测</RouterLink>
        <RouterLink v-if="session" to="/manage"><LayoutDashboard :size="16" /> 服务器管理</RouterLink>
        <RouterLink v-if="session?.user.scopes.includes('users.admin')" to="/users"><UsersRound :size="16" /> 用户</RouterLink>
        <RouterLink v-if="session?.user.scopes.includes('site.admin')" to="/site-settings"><Palette :size="16" /> 站点设置</RouterLink>
        <RouterLink v-if="session" to="/account"><Settings2 :size="16" /> 账户</RouterLink>
      </nav>
      <div v-if="session" class="identity">
        <span>{{ session.user.username }} <small>{{ session.user.role }}</small></span>
        <button class="secondary" :disabled="pending" @click="signOut"><LogOut :size="16" /> 退出</button>
      </div>
      <RouterLink v-else class="button secondary login-link" to="/login"><LogIn :size="16" /> 登录</RouterLink>
    </div>
  </header>
  <p v-if="error && session" class="notice shell" role="alert">{{ error }}</p>
  <RouterView v-slot="{ Component, route }">
    <Transition name="page">
      <component :is="Component" :key="route.path" />
    </Transition>
  </RouterView>
</template>
