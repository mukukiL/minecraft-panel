import { createApp, watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Dashboard from './Dashboard.vue'
import Login from './Login.vue'
import Monitor from './Monitor.vue'
import Users from './Users.vue'
import Account from './Account.vue'
import SiteSettings from './SiteSettings.vue'
import GameConfig from './GameConfig.vue'
import { loadBranding } from './branding'
import { restore, session } from './session'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/', component: Monitor, meta: { public: true } },
    { path: '/manage', component: Dashboard },
    { path: '/users', component: Users, meta: { scope: 'users.admin' } },
    { path: '/account', component: Account },
    { path: '/site-settings', component: SiteSettings, meta: { scope: 'site.admin' } },
    { path: '/game-config', component: GameConfig, meta: { scope: 'server.config' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
let restored = false
router.beforeEach(async to => {
  if (!restored) {
    restored = true
    try { await restore() } catch { session.value = null }
  }
  if (!session.value) return to.meta.public ? true : '/login'
  if (to.path === '/login') return '/manage'
  if (to.meta.scope && !session.value.user.scopes.includes(String(to.meta.scope))) return '/'
  return true
})
watch(session, value => {
  if (!value && !router.currentRoute.value.meta.public) void router.replace('/login')
})
createApp(App).use(router).mount('#app')
void loadBranding().catch(() => { /* The default branding remains available during outages. */ })
