export type Stage = '1新需求' | '2处理中' | '3待验收' | '4已归档'
export interface Project { id: string; manifestId: string; name: string; root: string }
export interface Registry { projects: Project[]; active: string | null }
export interface Revision { goal?: string; criteria?: string[]; reviewer?: string }
export interface Entry {
  type: 'note' | 'move' | 'amend'; key: string; actor: string; time: string; reason: string;
  from?: Stage; to?: Stage; evidence?: string[]; changes?: Revision
}
export interface Task {
  targetVersion: string
  id: string; code: string; title: string; role: string; stage: Stage; goal: string;
  reviewer: string; criteria: string[]; source: string; events: Entry[]
}
export interface Report { file: string; modified: number; url: string; kind?: 'user' | 'dev'; version?: string; revision?: string }
export type RoleFile = { text: string; error?: never } | { error: string; text?: never }
export interface Profile {
  name: string; agent: RoleFile; memory: RoleFile; reports: Report[]
  memoryUsage?: { bytes: number; limit: number }
}
export interface Snapshot {
  currentVersion: string
  versions: string[]
  profiles?: Profile[];
  name: string; roles: string[]; tasks: Task[]; reports: Report[]; warnings: {path: string; message: string}[]
}
export const stages: Stage[] = ['1新需求', '2处理中', '3待验收', '4已归档']
export function dateTime(value: string | number) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

