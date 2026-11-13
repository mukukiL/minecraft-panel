<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, explain, session, type Role, type User } from './session'

const roles: Role[] = ['viewer', 'operator', 'admin']
const rows = ref<User[]>([])
const cursor = ref<number | null>(null)
const username = ref('')
const password = ref('')
const role = ref<Role>('viewer')
const busy = ref(false)
const error = ref('')
const resetting = ref<User>()
const replacement = ref('')

async function load(after = 0) {
  const page = await api<{ items: User[]; next_cursor: number | null }>('/users?after=' + after)
  rows.value = after ? [...rows.value, ...page.items] : page.items
  cursor.value = page.next_cursor
}
async function handle(job: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await job() } catch (err) { error.value = explain(err) }
  finally { busy.value = false }
}
async function create() {
  try {
    await api('/users', { method: 'POST', body: JSON.stringify({
      username: username.value, password: password.value, role: role.value,
    }) })
    username.value = ''
    role.value = 'viewer'
    await load()
  } finally { password.value = '' }
}
async function edit(user: User, changes: { role?: Role; enabled?: boolean }) {
  const updated = await api<User>('/users/' + user.id, { method: 'PATCH', body: JSON.stringify(changes) })
  rows.value = rows.value.map(row => row.id === updated.id ? updated : row)
  if (session.value?.user.id === user.id && (updated.role !== user.role || !updated.enabled)) {
    session.value = null
  }
}
async function reset() {
  if (!resetting.value) return
  const id = resetting.value.id
  try {
    await api('/users/' + id + '/password', { method: 'POST', body: JSON.stringify({ password: replacement.value }) })
    resetting.value = undefined
    if (session.value?.user.id === id) session.value = null
  } finally { replacement.value = '' }
}
onMounted(() => handle(load))
</script>

<template>
  <main class="shell">
    <div class="heading"><h1>用户管理</h1></div>
    <p v-if="error" role="alert" class="notice">{{ error }}</p>
    <section class="card">
      <h2>添加用户</h2>
      <form class="form-grid" @submit.prevent="handle(create)">
        <label>用户名<input v-model.trim="username" pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{2,31}" autocomplete="off" required></label>
        <label>初始密码<input v-model="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label>
        <label>角色<select v-model="role"><option v-for="item in roles" :key="item">{{ item }}</option></select></label>
        <button :disabled="busy">创建</button>
      </form>
    </section>
    <section class="card">
      <h2>现有用户</h2>
      <div class="table-scroll">
        <table>
          <thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="user in rows" :key="user.id">
              <td>{{ user.username }}</td>
              <td><select :aria-label="user.username + ' 的角色'" :value="user.role" :disabled="busy"
                @change="(event) => { const select = event.target as HTMLSelectElement; const role = select.value as Role; select.value = user.role; handle(() => edit(user, { role })) }">
                <option v-for="item in roles" :key="item">{{ item }}</option>
              </select></td>
              <td>{{ user.enabled ? '启用' : '禁用' }}</td>
              <td><div class="actions">
                <button class="secondary" :disabled="busy" @click="handle(() => edit(user, { enabled: !user.enabled }))">{{ user.enabled ? '禁用' : '启用' }}</button>
                <button class="secondary" :disabled="busy" @click="resetting = user; replacement = ''">重置密码</button>
              </div></td>
            </tr>
          </tbody>
        </table>
      </div>
      <button v-if="cursor !== null" class="secondary" :disabled="busy" @click="handle(() => load(cursor ?? 0))">加载更多</button>
    </section>
    <section v-if="resetting" class="card">
      <h2>重置 {{ resetting.username }} 的密码</h2>
      <form class="actions" @submit.prevent="handle(reset)">
        <label>新密码<input v-model="replacement" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label>
        <button :disabled="busy">确认重置</button>
        <button class="secondary" type="button" @click="resetting = undefined; replacement = ''">取消</button>
      </form>
    </section>
  </main>
</template>
