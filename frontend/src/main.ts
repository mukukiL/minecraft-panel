import { createApp, watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Dashboard from './Dashboard.vue'
import Login from './Login.vue'
import Users from './Users.vue'
import Account from './Account.vue'
import { restore, session } from './session'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: Login },
    { path: '/', component: Dashboard },
    { path: '/users', component: Users, meta: { scope: 'users.admin' } },
    { path: '/account', component: Account },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
let restored = false
router.beforeEach(async to => {
  if (!restored) {
    restored = true
    try { await restore() } catch { session.value = null }
  }
  if (!session.value) return to.path === '/login' ? true : '/login'
  if (to.path === '/login') return '/'
  if (to.meta.scope && !session.value.user.scopes.includes(String(to.meta.scope))) return '/'
  return true
})
watch(session, value => {
  if (!value && router.currentRoute.value.path !== '/login') void router.replace('/login')
})
createApp(App).use(router).mount('#app')
