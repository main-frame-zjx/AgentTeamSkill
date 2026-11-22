<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Archive, ArrowUpRight, Boxes, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, CircleDot, ClipboardCheck, Columns3, Folder, FolderOpen, FolderPlus, HardDrive, Layers3, MapPin, Menu, MoreHorizontal, PackageOpen, Plus, RefreshCw, TriangleAlert, UserRound, UsersRound, X } from '@lucide/vue'
import ReportList from './ReportList.vue'
import TaskDetail from './TaskDetail.vue'
import TeamRoles from './TeamRoles.vue'
import { stages, type Registry, type Snapshot, type Task } from './types'

const registry = ref<Registry>({ projects: [], active: null })
const active = computed(() => registry.value.projects.find(p => p.id === registry.value.active))
const data = ref<Snapshot | null>(null)
const tab = ref<'tasks'|'roles'|'reports'>('tasks')
const role = ref('')
const versionChoice = ref('current')
const versionFilter = computed({
  get: () => versionChoice.value === 'current' && !data.value?.currentVersion ? 'all' : versionChoice.value,
  set: (choice: string) => { versionChoice.value = choice }
})
const versionTasks = computed(() => {
  const tasks = data.value?.tasks ?? []
  if (versionFilter.value === 'all') return tasks
  let target: string | null = versionFilter.value
  if (target === 'current') target = data.value?.currentVersion ?? null
  if (target === 'unbound') target = null
  return tasks.filter(t => t.targetVersion === target)
})
const numberedOptions = computed(() => {
  const choices = (data.value?.versions ?? []).filter(v => v !== data.value?.currentVersion || v === versionChoice.value)
  if (versionChoice.value.startsWith('v') && !choices.includes(versionChoice.value)) choices.push(versionChoice.value)
  return choices
})
const selected = ref('')
const selectedTask = computed(() => data.value?.tasks.find(t => t.id === selected.value))
const error = ref(''), unavailable = ref('')
const actionBusy = ref(false), refreshing = ref(false), ready = ref(false)
const sidebar = ref(false), actions = ref(false)
const updated = ref('')
const icons = [CircleDashed, CircleDot, ClipboardCheck, Archive]
const visibleTasks = computed(() => versionTasks.value.filter(t => !role.value || t.role === role.value))
const columns = computed(() => stages.map(stage => visibleTasks.value.filter(t => t.stage === stage)))
let timer: ReturnType<typeof setInterval>
let generation = 0

async function api<T>(url: string, post = false): Promise<T> {
  const response = await fetch(url, post ? { method: 'POST', headers: { 'X-Board-Request': '1' } } : {})
  const body = await response.json()
  if (!response.ok) throw new Error(body.error || '读取失败')
  return body
}
function message(e: unknown) { return e instanceof Error ? e.message : String(e) }
async function refresh() {
  const id = active.value?.id
  if (!id || refreshing.value) return
  const stamp = ++generation
  refreshing.value = true
  try {
    const query = tab.value === 'roles' ? '?profiles=1' : ''
    const snapshot = await api<Snapshot>('/api/projects/' + id + '/snapshot' + query)
    if (generation !== stamp) return
    data.value = snapshot
    if (!snapshot.roles.includes(role.value)) role.value = ''
    unavailable.value = ''
    updated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (e) {
    if (generation === stamp) { unavailable.value = message(e); data.value = null; selected.value = '' }
  } finally {
    if (generation === stamp) refreshing.value = false
  }
}
watch(tab, (next, previous) => {
  if (next !== 'roles' && previous !== 'roles') return
  generation++; refreshing.value = false
  void refresh()
})
watch(() => registry.value.active, () => {
  versionChoice.value = 'current'
  generation++; refreshing.value = false; data.value = null; role.value = ''; selected.value = ''
  updated.value = ''; unavailable.value = ''; tab.value = 'tasks'; actions.value = false
  void refresh()
}, { flush: 'sync' })
async function load() {
  try { registry.value = await api<Registry>('/api/projects'); error.value = '' }
  catch (e) { error.value = message(e) }
  ready.value = true
}
async function act(suffix: string) {
  if (actionBusy.value) return
  actions.value = false; actionBusy.value = true; error.value = ''
  try {
    const before = registry.value.active
    registry.value = await api<Registry>('/api/projects/' + suffix, true)
    if (before === registry.value.active) await refresh()
    sidebar.value = false
  } catch (e) { error.value = message(e) }
  finally { actionBusy.value = false }
}
function removeProject() {
  if (active.value && window.confirm('从看板列表移除「' + active.value.name + '」？项目文件会保留。')) void act(active.value.id + '/remove')
}
function onVisible() { if (document.visibilityState === 'visible') void refresh() }
function pillColor(task: Task) { return 'role-' + ((data.value?.roles.indexOf(task.role) || 0) % 5) }
onMounted(() => {
  void load()
  document.addEventListener('visibilitychange', onVisible)
  timer = setInterval(onVisible, 5000)
})
onUnmounted(() => { clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); generation++ })
</script>

<template>
  <div class="app-shell">
    <button v-if="sidebar" class="scrim" aria-label="关闭项目列表" @click="sidebar = false"></button>
    <aside class="sidebar" :class="{ shown: sidebar }">
      <div class="brand"><div class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></div><span>Agent Team <b>Board</b></span></div>
      <div class="side-main">
        <div class="side-heading"><span>我的项目</span><span class="side-count">{{ registry.projects.length }}</span></div>
        <button class="add-project" :disabled="actionBusy" @click="act('add')"><Plus :size="17"/>添加项目</button>
        <nav aria-label="项目列表">
          <button v-for="p in registry.projects" :key="p.id" class="project-item" :class="{ current: active?.id === p.id }" :title="p.root" :aria-current="active?.id === p.id ? 'page' : undefined" :disabled="actionBusy" @click="act(p.id + '/select')">
            <Folder :size="17"/><span><b>{{ p.id === active?.id && data ? data.name : p.name }}</b><small>{{ p.root }}</small></span>
          </button>
        </nav>
      </div>
      <div class="side-foot"><HardDrive :size="17"/><span>本机工作区</span></div>
    </aside>
    <main>
      <header class="topbar">
        <button class="icon-btn mobile-only" aria-label="项目列表" @click="sidebar = true"><Menu :size="19"/></button>
        <div class="crumb"><Layers3 :size="16"/><span>工作区</span><ChevronRight :size="14"/><strong>{{ data?.name || active?.name || '我的项目' }}</strong></div>
        <button v-if="active" class="btn refresh" :disabled="refreshing" @click="refresh"><RefreshCw :size="15" :class="{ spin: refreshing }"/>刷新</button>
      </header>
      <div class="content">
        <div v-if="error" class="notice" role="alert"><TriangleAlert :size="18"/><span>{{ error }}</span><button v-if="!active" class="text-btn" @click="load">重试读取列表</button><button class="icon-btn" aria-label="关闭提示" @click="error = ''"><X :size="15"/></button></div>
        <div v-if="!ready" class="empty">正在加载工作区…</div>
        <div v-else-if="!active" class="welcome">
          <div class="welcome-icon"><FolderPlus :size="36" :stroke-width="1.5"/></div>
          <h1>添加第一个项目</h1>
          <p>选择含有 AT.json 的项目文件夹，查看团队需求与发布成果。</p>
          <button class="primary-btn" :disabled="actionBusy" @click="act('add')"><Plus :size="17"/>{{ actionBusy ? '正在选择文件夹…' : '选择项目文件夹' }}</button>
        </div>
        <template v-else>
          <div class="project-head">
            <div class="project-emblem"><Boxes :size="28" :stroke-width="1.7"/></div>
            <div class="project-title">
              <div class="title-line"><h1>{{ data?.name || active.name }}</h1><span v-if="data" class="chip">{{ data.currentVersion ? '当前版本 ' + data.currentVersion : '未设置当前版本' }}</span></div>
              <p :title="active.root"><FolderOpen :size="14"/>{{ active.root }}</p>
            </div>
            <div class="actions"><button class="icon-btn" aria-label="项目选项" :aria-expanded="actions" @click="actions = !actions"><MoreHorizontal :size="21"/></button>
              <template v-if="actions"><button class="menu-backdrop" aria-label="关闭项目选项" @click="actions = false"></button><div class="action-list"><button @click="act(active.id + '/relocate')">重新定位项目</button><button @click="removeProject">从列表移除</button></div></template>
            </div>
          </div>
          <div class="tabs" aria-label="项目视图">
            <button :class="{ chosen: tab === 'tasks' }" :aria-pressed="tab === 'tasks'" @click="tab = 'tasks'"><Columns3 :size="17"/>需求看板</button>
            <button :class="{ chosen: tab === 'roles' }" :aria-pressed="tab === 'roles'" @click="tab = 'roles'"><UsersRound :size="17"/>团队角色</button>
            <button :class="{ chosen: tab === 'reports' }" :aria-pressed="tab === 'reports'" @click="tab = 'reports'"><PackageOpen :size="17"/>发布成果</button>
            <div v-if="data && tab !== 'reports'" class="version-control">
              <label for="version-filter">查看版本</label>
              <span class="select-wrap"><select id="version-filter" v-model="versionFilter">
                <option v-if="data.currentVersion" value="current">当前版本 · {{ data.currentVersion }}</option>
                <option v-for="v in numberedOptions" :key="v" :value="v">{{ v }}</option>
                <option v-if="data.tasks.some(t => t.targetVersion === null) || versionFilter === 'unbound'" value="unbound">未绑定版本</option>
                <option value="all">全部版本</option>
              </select><ChevronDown :size="14"/></span>
            </div>
          </div>
          <div v-if="unavailable" class="empty"><MapPin :size="28"/><h2>项目暂时无法读取</h2><p>{{ unavailable }}</p><button class="btn" :disabled="actionBusy" @click="act(active.id + '/relocate')">重新定位</button></div>
          <div v-else-if="!data" class="empty">正在读取项目…</div>
          <template v-else>
            <details v-if="data.warnings.length" class="warnings"><summary>有 {{ data.warnings.length }} 项读取异常</summary><p v-for="(w,i) in data.warnings" :key="i">{{ w.path }} · {{ w.message }}</p></details>
            <template v-if="tab === 'tasks'">
              <div class="board-toolbar"><div class="toolbar-title"><h2>团队需求</h2><span class="total">{{ visibleTasks.length }}</span></div>
                <label class="select-wrap"><UsersRound :size="16"/><select v-model="role" aria-label="筛选所属角色"><option value="">全部角色</option><option v-for="r in data.roles" :key="r" :value="r">{{ r }}</option></select><ChevronDown :size="14"/></label>
              </div>
              <p v-if="versionFilter !== 'all' && !versionTasks.length" class="version-empty">该版本暂无需求</p>
              <div class="lanes">
                <section v-for="(stage,i) in stages" :key="stage" class="lane" :class="'lane-' + i" :aria-label="stage.slice(1)">
                  <header><component :is="icons[i]" :size="17"/><h3>{{ stage.slice(1) }}</h3><span>{{ columns[i].length }}</span></header>
                  <div class="cards">
                    <button v-for="t in columns[i]" :key="t.id" class="task-card" @click="selected = t.id">
                      <div class="card-meta"><code>{{ t.code || t.id.slice(0,11) }}</code><ArrowUpRight :size="15"/></div>
                      <strong>{{ t.title }}</strong>
                      <span class="role-pill" :class="pillColor(t)"><UserRound :size="12"/>{{ t.role }}</span>
                      <span v-if="versionFilter === 'all'" class="task-version">{{ t.targetVersion ?? '未绑定版本' }}</span>
                    </button>
                    <div v-if="!columns[i].length" class="empty-column">暂无需求</div>
                  </div>
                </section>
              </div>
            </template>
            <TeamRoles v-else-if="tab === 'roles'" :profiles="data.profiles" :tasks="versionTasks" :show-versions="versionFilter === 'all'" @open-task="id => selected = id"/>
            <template v-else>
              <div class="board-toolbar"><div class="toolbar-title"><h2>HTML 发布成果</h2><span class="total">{{ data.reports.length }}</span></div></div>
              <div v-if="!data.reports.length" class="empty publish-empty"><div class="welcome-icon"><PackageOpen :size="29"/></div><h2>暂无 HTML 发布成果</h2><p>项目负责人发布用户指南或甲方总览后，可在这里查看。</p></div>
              <ReportList v-else :reports="data.reports"/>
            </template>
            <div class="sync"><CheckCircle2 :size="14"/>已刷新 <time>{{ updated }}</time></div>
          </template>
        </template>
      </div>
    </main>
    <TaskDetail v-if="selected" :task="selectedTask" @close="selected = ''"/>
  </div>
</template>

