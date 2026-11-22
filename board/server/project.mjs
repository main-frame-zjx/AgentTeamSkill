import { readFile, readdir, realpath, stat } from 'node:fs/promises'
import path from 'node:path'

export const stages = ['1新需求', '2处理中', '3待验收', '4已归档']

function inside(root, file) {
  const relative = path.relative(root, file)
  if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
    throw new Error('路径超出允许访问的目录')
  }
}

export async function resolveInside(root, ...parts) {
  const file = path.resolve(root, ...parts)
  inside(root, file)
  const resolved = await realpath(file)
  inside(root, resolved)
  return resolved
}

export async function roleReportRoot(root, directory) {
  const expected = path.resolve(root, directory, 'report')
  const folder = await resolveInside(root, directory, 'report')
  if (path.relative(expected, folder)) throw new Error('角色报告目录已重定向')
  return folder
}

async function reportFile(root, parts, base) {
  const info = await stat(await resolveInside(root, ...parts))
  if (!info.isFile()) throw new Error('报告入口不是文件')
  return { file: parts.join('/'), modified: info.mtimeMs, url: base + '/' + parts.map(encodeURIComponent).join('/') }
}

function latestReports(a, b) {
  return b.modified - a.modified || a.file.localeCompare(b.file, 'zh-CN')
}

async function roleReports(project, member, reportBase, warnings) {
  const relative = path.join(member.dir, 'report')
  const base = reportBase + '/role/' + project.id + '/' + encodeURIComponent(member.dir)
  const reports = []
  try {
    const folder = await roleReportRoot(project.root, member.dir)
    for (const file of await readdir(folder, { withFileTypes: true })) {
      if (!file.isFile() || !/\.html?$/i.test(file.name)) continue
      try {
        reports.push(await reportFile(folder, [file.name], base))
      } catch (error) {
        warnings.push({ path: path.join(relative, file.name), message: error.message })
      }
    }
  } catch (error) {
    if (error.code !== 'ENOENT') warnings.push({ path: relative, message: error.message })
  }
  return reports.sort(latestReports)
}

export async function manifest(root) {
  let raw
  try {
    raw = await readFile(await resolveInside(root, 'AT.json'), 'utf8')
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('请选择包含 AT.json 的项目根目录')
    throw error
  }
  let data
  try {
    data = JSON.parse(raw.replace(/^\uFEFF/, ''))
  } catch {
    throw new Error('AT.json 不是有效的 JSON 文件')
  }
  if (data?.format !== 'agent-team/v2' || !data.name || !data.id ||
      typeof data.name !== 'string' || typeof data.id !== 'string' || !Array.isArray(data.members)) {
    throw new Error('AT.json 缺少 agent-team/v2 项目所需的格式、名称、标识或角色列表')
  }
  for (const role of data.members) {
    if (typeof role?.name !== 'string' || !role.name || typeof role.dir !== 'string' ||
        !role.dir || /[\\/:]/.test(role.dir) || ['.', '..'].includes(role.dir)) {
      throw new Error('AT.json 中的角色名称或目录无效')
    }
  }
  return data
}

function stringList(value) {
  return Array.isArray(value) && value.every(x => typeof x === 'string')
}

// Match the AT numeric version identity, including components beyond JS number precision.
function version(value) {
  if (typeof value !== 'string' || value.length > 64 || !/^v?\d+(?:\.\d+)*$/i.test(value.trim())) {
    throw new Error('版本号应为数字版本，例如 v1.10')
  }
  const parts = value.trim().replace(/^v/i, '').split('.').map(n => String(BigInt(n)))
  while (parts.length > 2 && parts.at(-1) === '0') parts.pop()
  if (parts.length === 1) parts.push('0')
  return 'v' + parts.join('.')
}

function newestFirst(a, b) {
  const left = a.slice(1).split('.').map(BigInt)
  const right = b.slice(1).split('.').map(BigInt)
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    if (left[i] !== right[i]) return left[i] > right[i] ? -1 : 1
  }
  return right.length - left.length
}

function checkDetails(spec) {
  if (typeof spec.goal !== 'string' || typeof spec.reviewer !== 'string' || !stringList(spec.criteria)) {
    throw new Error('目标、验收人或验收条件格式错误')
  }
}

function parseTask(raw, file, stage, role) {
  const lines = raw.replace(/^\uFEFF/, '').split(/\r?\n/)
  const blocks = []
  let json = null
  for (const line of lines) {
    if (json === null && line === '\x60\x60\x60json') json = []
    else if (json !== null && line === '\x60\x60\x60') {
      blocks.push(JSON.parse(json.join('\n')))
      json = null
    } else if (json !== null) json.push(line)
  }
  const [spec, ...events] = blocks
  if (json !== null || spec?.format !== 'agent-team/task-v1' || !/^AT-[a-f0-9]{32}$/.test(spec.id)
      || spec.owner !== role || typeof spec.title !== 'string') {
    throw new Error('需求格式、编号或所属角色不匹配')
  }
  checkDetails(spec)
  let targetVersion = spec.version
  const current = { goal: spec.goal, criteria: spec.criteria, reviewer: spec.reviewer }
  for (const event of events) {
    if (!['note', 'move', 'amend'].includes(event?.type) || typeof event.reason !== 'string'
        || typeof event.actor !== 'string' || typeof event.time !== 'string') throw new Error('追加记录格式错误')
    if (event.type === 'amend') {
      if (!event.changes || Object.keys(event.changes).some(k => !Object.hasOwn(current, k))) throw new Error('修订字段无效')
      Object.assign(current, event.changes)
      checkDetails(current)
    }
    if (event.type === 'note' && Object.hasOwn(event, 'version')) targetVersion = event.version
    if (event.type === 'move' && (!stages.includes(event.from) || !stages.includes(event.to)
        || (event.evidence !== undefined && !stringList(event.evidence)))) throw new Error('流转记录无效')
  }
  return { id: spec.id, code: /^AT-([A-Za-z]+\d{5})-/.exec(file)?.[1] ?? '',
    title: spec.title, role, stage, source: spec.source ?? '', targetVersion: targetVersion == null ? null : version(targetVersion),
    ...current, events }
}

async function roleFile(root, directory, name) {
  try {
    const file = await resolveInside(root, directory, name)
    const text = (await readFile(file, 'utf8')).replace(/^\uFEFF/, '')
    return { text }
  } catch (error) {
    return { error: error.code === 'ENOENT' ? '未找到 ' + name : '无法读取 ' + name + '：' + error.message }
  }
}

export async function snapshot(project, reportBase, includeProfiles = false) {
  const { root } = project
  const data = await manifest(root)
  if (data.id !== project.manifestId) throw new Error('此路径的 AT.json 已指向其他项目，请重新定位')
  const tasks = [], warnings = [], reports = [], seen = new Set()
  let currentVersion = null
  if (data.current_version != null) {
    try {
      currentVersion = version(data.current_version)
    } catch (error) {
      warnings.push({ path: 'AT.json', message: error.message })
    }
  }
  const versions = new Set(currentVersion ? [currentVersion] : [])
  const historyPath = '.at-state/releases.json'
  const historicalEntries = new Set()
  try {
    const history = JSON.parse(await readFile(await resolveInside(root, historyPath), 'utf8'))
    if (!Array.isArray(history)) throw new Error('发布历史应为数组')
    for (const release of history) {
      versions.add(version(release?.version))
      if (typeof release.entry === 'string' && /^publish\/.+\.html?$/i.test(release.entry)) {
        const relative = release.entry.slice('publish/'.length)
        if (relative.split('/').every(p => p && p !== '.' && p !== '..' && !/[\\:]/.test(p))) historicalEntries.add(relative)
      }
    }
  } catch (error) {
    if (error.code !== 'ENOENT') warnings.push({ path: historyPath, message: error.message })
  }
  const readDirectory = async relative => {
    try {
      const folder = await resolveInside(root, relative)
      return await readdir(folder, { withFileTypes: true })
    } catch (error) {
      warnings.push({ path: relative, message: error.message })
      return []
    }
  }
  for (const member of data.members) {
    for (const stage of stages) {
      const dir = path.join(member.dir, 'workspace', stage)
      const files = await readDirectory(dir)
      for (const file of files.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))) {
        if (!file.isFile() || !/\.md$/i.test(file.name)) continue
        const relative = path.join(dir, file.name)
        try {
          const raw = await readFile(await resolveInside(root, relative), 'utf8')
          const task = parseTask(raw, file.name, stage, member.name)
          if (seen.has(task.id)) throw new Error('需求编号重复')
          tasks.push(task)
          if (task.targetVersion) versions.add(task.targetVersion)
          seen.add(task.id)
        } catch (error) {
          warnings.push({ path: relative, message: error.message })
        }
      }
    }
  }
  const addReport = async (parts, metadata = {}) => {
    const file = parts.join('/')
    try {
      const publicRoot = await resolveInside(root, 'publish')
      reports.push({ ...await reportFile(publicRoot, parts, reportBase + '/' + project.id), ...metadata })
      historicalEntries.delete(file)
    } catch (error) {
      if (error.code !== 'ENOENT') warnings.push({ path: path.join('publish', file), message: error.message })
    }
  }
  for (const file of await readDirectory('publish')) {
    if (!file.isDirectory() || !['user', 'dev'].includes(file.name)) continue
    const kind = file.name
    for (const folder of await readDirectory(path.join('publish', kind))) {
      if (!folder.isDirectory() || !/^v\d+(?:\.\d+)+$/.test(folder.name)) continue
      for (const revision of await readDirectory(path.join('publish', kind, folder.name))) {
        if (!revision.isDirectory() || !/^r[1-9]\d*$/.test(revision.name)) continue
        await addReport([kind, folder.name, revision.name, 'index.html'],
          { kind, version: folder.name, revision: revision.name })
      }
    }
  }
  for (const file of historicalEntries) await addReport(file.split('/'))
  reports.sort(latestReports)
  const result = { name: data.name, currentVersion, versions: [...versions].sort(newestFirst),
    roles: data.members.map(m => m.name), tasks, warnings, reports }
  if (includeProfiles) {
    result.profiles = await Promise.all(data.members.map(async member => {
      const [agent, memory, reports] = await Promise.all([
        roleFile(root, member.dir, 'Agent.md'), roleFile(root, member.dir, 'Memory.md'),
        roleReports(project, member, reportBase, warnings)
      ])
      return { name: member.name, agent, memory, reports }
    }))
  }
  return result
}

