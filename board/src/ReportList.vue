<script setup lang="ts">
import { ExternalLink, FileCode2 } from '@lucide/vue'
import { dateTime, type Report } from './types'
defineProps<{ reports: Report[] }>()
</script>

<template>
  <div class="report-list">
    <a v-for="report in reports" :key="report.file" :href="report.url" target="_blank" rel="noopener noreferrer">
      <div class="report-icon"><FileCode2 :size="22"/></div>
      <span>
        <strong v-if="report.kind">{{ report.kind === 'user' ? '用户指南' : '甲方项目总览' }} · {{ report.version }} · {{ report.revision }}</strong>
        <strong v-else>{{ report.file }}</strong>
        <small>{{ dateTime(report.modified) }}</small>
      </span>
      <ExternalLink :size="17"/>
    </a>
  </div>
</template>
