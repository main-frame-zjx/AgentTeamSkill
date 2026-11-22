<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CheckCheck, X, History, FileText } from '@lucide/vue'
import { dateTime, type Task } from './types'
defineProps<{ task?: Task }>()
const emit = defineEmits<{ close: [] }>()
const drawer = ref<HTMLDialogElement>()
onMounted(() => drawer.value?.showModal())
const eventNames = { note: '追加说明', move: '状态流转', amend: '需求修订' }
</script>

<template>
  <dialog ref="drawer" class="drawer" aria-labelledby="detail-heading" @cancel.prevent="emit('close')" @click="e => { if (e.target === drawer) emit('close') }">
    <article class="drawer-inner">
      <div class="drawer-top"><span><FileText :size="17"/>需求详情</span><button class="icon-btn" aria-label="关闭详情" autofocus @click="emit('close')"><X :size="20"/></button></div>
      <template v-if="task">
        <div class="drawer-meta"><span class="chip">{{ task.stage.slice(1) }}</span><code>{{ task.code || task.id }}</code></div>
        <h2 id="detail-heading">{{ task.title }}</h2>
        <dl class="facts"><dt>目标版本</dt><dd>{{ task.targetVersion ?? '未绑定版本' }}</dd><dt>所属角色</dt><dd>{{ task.role }}</dd><dt>验收人</dt><dd>{{ task.reviewer }}</dd><dt>来源</dt><dd>{{ task.source }}</dd><dt>需求编号</dt><dd><code>{{ task.id }}</code></dd></dl>
        <section><h3>当前目标</h3><p>{{ task.goal }}</p></section>
        <section><h3><CheckCheck :size="17"/>验收条件</h3><ol><li v-for="(criterion,i) in task.criteria" :key="i">{{ criterion }}</li></ol></section>
        <section><h3><History :size="17"/>追加记录 <small>{{ task.events.length }}</small></h3>
          <p v-if="!task.events.length" class="muted">暂无追加记录</p>
          <div v-for="event in task.events" :key="event.key" class="history-item">
            <strong>{{ eventNames[event.type] }}</strong> · {{ event.actor }}
            <time>{{ dateTime(event.time) }}</time>
            <p v-if="event.type === 'move'">{{ event.from?.slice(1) }} → {{ event.to?.slice(1) }}</p>
            <p>{{ event.reason }}</p>
            <template v-if="event.changes">
              <p v-if="event.changes.goal"><b>目标</b>　{{ event.changes.goal }}</p>
              <p v-if="event.changes.reviewer"><b>验收人</b>　{{ event.changes.reviewer }}</p>
              <template v-if="event.changes.criteria"><b>验收条件</b><ul><li v-for="(line,i) in event.changes.criteria" :key="i">{{ line }}</li></ul></template>
            </template>
            <template v-if="event.evidence?.length"><b>验收证据</b><ul><li v-for="(line,i) in event.evidence" :key="i">{{ line }}</li></ul></template>
          </div>
        </section>
      </template>
      <h2 v-else id="detail-heading">当前快照中未找到此需求</h2>
    </article>
  </dialog>
</template>

