<script setup lang="ts">
import { computed, ref } from 'vue'
import { BookOpen, ClipboardList, ChevronRight, FileText, ListChecks, NotebookPen, UserRound, UsersRound } from '@lucide/vue'
import ReportList from './ReportList.vue'
import MarkdownIt from 'markdown-it'
import { stages, type Profile, type Task } from './types'

const props = defineProps<{ profiles?: Profile[]; tasks: Task[]; showVersions: boolean }>()
const emit = defineEmits<{ openTask: [id: string] }>()
const selected = ref('')
const section = ref<'agent' | 'memory' | 'tasks' | 'reports'>('agent')
const profile = computed(() => props.profiles?.find(p => p.name === selected.value) || props.profiles?.[0])
const owned = computed(() => props.tasks.filter(t => t.role === profile.value?.name))
const groups = computed(() => stages.map(stage => ({ stage, tasks: owned.value.filter(t => t.stage === stage) })))
const counts = computed(() => {
  const result = new Map<string, number>()
  for (const task of props.tasks) result.set(task.role, (result.get(task.role) || 0) + 1)
  return result
})
const document = computed(() => section.value === 'agent' || section.value === 'memory' ? profile.value?.[section.value] : undefined)
const filename = computed(() => section.value === 'agent' ? 'Agent.md' : 'Memory.md')
const markdown = new MarkdownIt({ html: false }).disable('image')
markdown.validateLink = href => /^https?:\/\//i.test(href)
markdown.renderer.rules.link_open = (tokens, idx, options, env, renderer) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, idx, options)
}
const rendered = computed(() => markdown.render(document.value?.text || ''))
</script>

<template>
  <div v-if="!profiles" class="empty">正在读取角色档案…</div>
  <div v-else-if="!profile" class="empty"><UsersRound :size="28"/><h2>项目尚未登记角色</h2></div>
  <div v-else class="role-layout">
    <section class="roster">
      <div class="roster-heading"><h2>角色列表</h2><span class="total">{{ profiles.length }}</span></div>
      <nav aria-label="团队角色列表">
        <button v-for="(person,i) in profiles" :key="person.name" class="roster-item" :class="{ active: profile.name === person.name }" :aria-pressed="profile.name === person.name" @click="selected = person.name">
          <span class="avatar" :class="'role-' + i % 5"><UserRound :size="18"/></span>
          <span class="roster-name"><strong>{{ person.name }}</strong><small>{{ counts.get(person.name) || 0 }} 条需求</small></span>
          <ChevronRight :size="15"/>
        </button>
      </nav>
    </section>
    <section class="role-detail" :aria-label="profile.name + '的角色详情'">
      <header class="profile-head"><UserRound :size="20"/><h2>{{ profile.name }}</h2></header>
      <div class="profile-tabs" aria-label="角色详情分类">
        <button :aria-pressed="section === 'agent'" @click="section = 'agent'"><BookOpen :size="15"/>角色档案</button>
        <button :aria-pressed="section === 'memory'" @click="section = 'memory'"><NotebookPen :size="15"/>工作记忆</button>
        <button :aria-pressed="section === 'tasks'" @click="section = 'tasks'"><ListChecks :size="15"/>负责需求 <b>{{ owned.length }}</b></button>
        <button :aria-pressed="section === 'reports'" @click="section = 'reports'"><ClipboardList :size="15"/>阶段报告 <b>{{ profile.reports.length }}</b></button>
      </div>
      <template v-if="section === 'reports'">
        <p v-if="!profile.reports.length" class="role-empty">该角色暂无阶段报告</p>
        <ReportList v-else class="role-reports" :reports="profile.reports"/>
      </template>
      <template v-else-if="section !== 'tasks'">
        <div class="doc-file">
          <FileText :size="14"/><code>{{ filename }}</code>
          <span v-if="section === 'memory' && profile.memoryUsage">{{ profile.memoryUsage.bytes }} / {{ profile.memoryUsage.limit }} 字节</span>
        </div>
        <p v-if="document?.error" class="role-empty">{{ document.error }}</p>
        <p v-else-if="!document?.text?.trim()" class="role-empty">{{ filename }} 暂无内容</p>
        <div v-else class="role-markdown" v-html="rendered"></div>
      </template>
      <div v-else class="owned-tasks">
        <section v-for="group in groups" :key="group.stage">
          <h3>{{ group.stage.slice(1) }} <small>{{ group.tasks.length }}</small></h3>
          <button v-for="task in group.tasks" :key="task.id" class="owned-task" @click="emit('openTask', task.id)">
            <code>{{ task.code }}</code><span>{{ task.title }}</span>
            <span v-if="showVersions" class="task-version">{{ task.targetVersion }}</span><ChevronRight :size="15"/>
          </button>
          <p v-if="!group.tasks.length" class="muted">暂无需求</p>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.role-layout { display: grid; grid-template-columns: minmax(175px, 24%) minmax(0,1fr); align-items: start; gap: 18px; margin-top: 23px }
.roster,.role-detail { background: #fff; border: 1px solid var(--line); border-radius: 11px }
.roster { padding: 12px 8px }
.roster-heading,.profile-head,.profile-tabs,.roster-item,.doc-file,.owned-task,.profile-tabs button { display: flex; align-items: center; gap: 8px }
.roster-heading { padding: 3px 8px 12px }
.roster-heading h2 { font-size: 1rem }
.roster-item { text-align: left; width: 100%; padding: 10px 8px; border-radius: 7px; margin-top: 3px }
.roster-item.active { background: #e9f2e8; color: #285844 }
.roster-item:hover { background: #f1f5ee }
.avatar { display: grid; place-items: center; width: 32px; height: 34px; flex: none; background: #e6eee6; color: #4b6a55; border-radius: 6px }
.roster-name { flex: 1; min-width: 0; overflow-wrap: anywhere }
.roster-name strong { display: block; font-size: .9rem }
.roster-name small,.doc-file,.owned-tasks small { font-size: .78rem; color: var(--muted) }
.roster-item > svg { flex: none; opacity: 0 }
.roster-item.active > svg { opacity: 1 }
.role-detail { min-width: 0; padding: 21px clamp(14px,2vw,28px) 25px }
.profile-head { margin-bottom: 17px; color: #294d40 }
.profile-tabs { border-bottom: 1px solid var(--line); gap: 16px; flex-wrap: wrap }
.profile-tabs button { padding: 7px 0 10px; font-size: .9rem; border-bottom: 2px solid transparent; margin-bottom: -1px; color: var(--muted) }
.profile-tabs button[aria-pressed="true"] { color: var(--green); border-color: var(--green); font-weight: 600 }
.profile-tabs b { font-size: .78rem }
.doc-file { margin-top: 18px }
.role-markdown { color: #34453c; line-height: 1.75; overflow-wrap: anywhere; max-width: 84ch }
.role-markdown :deep(h1) { font-size: 1.18rem; letter-spacing: -.02em; margin-top: 10px }
.role-markdown :deep(h2),.role-markdown :deep(h3) { font-size: 1rem; margin: 20px 0 5px }
.role-markdown :deep(p),.role-markdown :deep(ol),.role-markdown :deep(ul) { margin: 8px 0; font-size: .94rem }
.role-markdown :deep(ol),.role-markdown :deep(ul) { padding-left: 23px }
.role-markdown :deep(a) { color: var(--green) }
.role-markdown :deep(pre),.role-markdown :deep(table) { display: block; max-width: 100%; overflow: auto }
.role-markdown :deep(pre) { background: #f3f5f1; padding: 12px; border-radius: 6px }
.role-markdown :deep(blockquote) { padding-left: 12px; border-left: 3px solid var(--line); margin: 10px 0 }
.role-markdown :deep(td),.role-markdown :deep(th) { padding: 3px 8px; border: 1px solid var(--line) }
.role-empty { margin-top: 18px; color: var(--muted); font-size: .93rem }
.role-reports { margin-top: 16px }
.owned-tasks section { margin-top: 18px }
.owned-tasks h3 { display: flex; align-items: center; gap: 8px; font-size: .96rem; margin-bottom: 7px }
.owned-tasks p { font-size: .85rem }
.owned-task { width: 100%; text-align: left; border-top: 1px solid #e7ece5; padding: 10px 3px; font-size: .91rem; overflow-wrap: anywhere }
.owned-task code { color: var(--muted) }
.owned-task svg { margin-left: auto }
.owned-task:hover { background: #f4f7f1 }
@media(max-width: 850px) {
  .role-layout { grid-template-columns: minmax(0,1fr) }
  .roster nav { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 2px }
}
@media(max-width: 430px) {
  .profile-tabs { gap: 10px }
  .profile-tabs button { gap: 4px }
  .roster-item { gap: 5px; padding: 7px 4px }
  .roster-item > svg { display: none }
}
</style>

