import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, rename, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { registry } from '../server/registry.mjs'
import { manifest, stages, snapshot } from '../server/project.mjs'
import { startBoard } from '../server/http.mjs'

async function fixture(t) {
  const dir = await mkdtemp(path.join(tmpdir(), 'at-board-'))
  t.after(() => rm(dir, { recursive: true, force: true }))
  const root = path.join(dir, '中文 项目')
  const config = path.join(dir, '设置')
  const member = { name: '工程师', dir: 'AT_工程师' }
  const meta = { format: 'agent-team/v2', name: '测试项目', id: 'project-1', members: [member] }
  const workspace = path.join(root, member.dir, 'workspace')
  for (const stage of stages) await mkdir(path.join(workspace, stage), { recursive: true })
  await mkdir(path.join(root, 'publish'))
  await writeFile(path.join(root, 'AT.json'), JSON.stringify(meta))
  return { dir, root, config, workspace, meta }
}

function taskDoc(number, events = [], version) {
  const id = 'AT-' + String(number).padStart(32, '0')
  const spec = { format: 'agent-team/task-v1', id, title: '示例需求', owner: '工程师', version,
    reviewer: '负责人', goal: '原目标', criteria: ['原验收条件'], source: '用户' }
  const fence = String.fromCharCode(96).repeat(3)
  const block = value => fence + 'json\r\n' + JSON.stringify(value, null, 2) + '\r\n' + fence + '\r\n'
  return { id, raw: '# ' + id + '\r\n\r\n## 需求\r\n\r\n' + block(spec) + '\r\n## 追加记录\r\n\r\n' + events.map(block).join('\r\n') }
}

test('登记路径去重、同名区分、恢复、重新定位和移除均只修改看板配置', async t => {
  const { dir, root, config, meta } = await fixture(t)
  const store = await registry(config)
  assert.equal(store.state().active, null)
  await assert.rejects(store.register(dir), /AT.json/)
  const first = (await store.register(root)).active
  await Promise.all([store.register(root), store.register(root)])
  assert.equal(store.state().projects.length, 1)
  const other = path.join(dir, 'other')
  await mkdir(other)
  await writeFile(path.join(other, 'AT.json'), JSON.stringify({ ...meta, id: 'project-2' }))
  const second = (await store.register(other)).active
  assert.notEqual(second, first)
  await store.select(first)
  const reopened = await registry(config)
  assert.deepEqual(reopened.state(), store.state())
  const moved = path.join(dir, '搬迁')
  await rename(root, moved)
  await assert.rejects(snapshot(reopened.find(first), ''), /AT.json/)
  await assert.rejects(reopened.register(other, first), /标识不同/)
  await reopened.register(moved, first)
  await reopened.remove(first)
  assert.equal(reopened.state().active, second)
  assert.equal((await manifest(moved)).id, meta.id)
})

test('四列、两种文件名、修订、退回与归档历史、单文件异常和同步重读', async t => {
  const { root, workspace, config } = await fixture(t)
  const store = await registry(config)
  await store.register(root)
  const project = store.find(store.state().active)
  const event = { time: '2026-11-21T04:05:06+00:00', actor: '工程师', reason: '说明' }
  const history = [
    { type: 'note' }, { type: 'move', from: stages[0], to: stages[1] },
    { type: 'amend', changes: { criteria: ['新条件'], goal: '新目标', reviewer: '用户' } },
    { type: 'move', from: stages[1], to: stages[2], evidence: ['首次送验'] },
    { type: 'move', from: stages[2], to: stages[1], evidence: ['退回原因'] },
    { type: 'move', from: stages[1], to: stages[2], evidence: ['再次送验'] },
    { type: 'move', from: stages[2], to: stages[3], evidence: ['验收通过'] }
  ].map((entry, i) => ({ ...event, key: String(i), ...entry }))
  for (const [i, stage] of stages.entries()) {
    const item = taskDoc(i, i === 3 ? history : [])
    const name = i === 0 ? item.id + '.md' : 'AT-Dev0000' + i + '-示例.md'
    await writeFile(path.join(workspace, stage, name), item.raw)
  }
  const read = () => snapshot(project, 'http://127.0.0.1:1')
  const first = await read()
  assert.deepEqual(first.tasks.map(t => t.stage), stages)
  assert.deepEqual(first.warnings, [])
  assert.equal(first.tasks[0].code, '')
  assert.equal(first.tasks[3].code, 'Dev00003')
  assert.deepEqual(first.tasks[3].criteria, ['新条件'])
  assert.equal(first.tasks[3].goal, '新目标')
  assert.equal(first.tasks[3].reviewer, '用户')
  assert.deepEqual(first.tasks[3].events, history)
  const file = first.tasks[0].id + '.md'
  await rename(path.join(workspace, stages[0], file), path.join(workspace, stages[1], file))
  await writeFile(path.join(workspace, stages[0], '坏文件.md'), 'xxxx')
  const next = await read()
  assert.equal(next.tasks.length, 4)
  assert.equal(next.tasks.find(t => t.id === first.tasks[0].id).stage, stages[1])
  assert.match(next.warnings[0].path, /坏文件/)
})

test('当前版本、补登记和发布历史共用数字版本标识，支持旧项目和后续迭代', async t => {
  const { root, meta, workspace } = await fixture(t)
  const read = () => snapshot({ root, id: 'local', manifestId: meta.id }, '')
  const note = { type: 'note', time: '2026-11-21', actor: '用户', reason: '补登记', key: 'bind', version: '1.10.0' }
  async function writeTask(index, events, target) {
    const task = taskDoc(index, events, target)
    await writeFile(path.join(workspace, stages[0], task.id + '.md'), task.raw)
  }
  await writeTask(1, [], 'V01.09')
  await writeTask(2, [note, { ...note, key: 'comment', version: undefined }])
  await writeTask(3, [], undefined)
  await writeTask(4, [], '2')
  const legacy = await read()
  assert.equal(legacy.currentVersion, null)
  assert.deepEqual(legacy.tasks.map(t => t.targetVersion), ['v1.9', 'v1.10', null, 'v2.0'])
  await writeFile(path.join(root, 'AT.json'), JSON.stringify({ ...meta, current_version: 'v1.10' }))
  await mkdir(path.join(root, '.at-state'))
  const history = path.join(root, '.at-state', 'releases.json')
  await writeFile(history, JSON.stringify([{ version: '0.99' }, { version: '1.9.0' }]))
  const current = await read()
  assert.deepEqual(current.versions, ['v2.0', 'v1.10', 'v1.9', 'v0.99'])
  assert.equal(current.tasks.filter(t => t.targetVersion === current.currentVersion).length, 1)
  assert.deepEqual(current.warnings, [])
  await writeFile(path.join(root, 'AT.json'), JSON.stringify({ ...meta, current_version: '2.10' }))
  assert.equal((await read()).tasks.filter(t => t.targetVersion === 'v2.10').length, 0)
  await writeTask(3, [{ ...note, version: '2.10' }])
  const next = await read()
  assert.equal(next.currentVersion, 'v2.10')
  assert.equal(next.tasks.filter(t => t.targetVersion === next.currentVersion).length, 1)
  await writeFile(history, '{')
  const damaged = await read()
  assert.equal(damaged.tasks.length, 4)
  assert.equal(damaged.warnings[0].path, '.at-state/releases.json')
})

test('角色档案按登记名单读取，保留 Markdown，记忆缺失和角色没有任务均可查看', async t => {
  const { root, config, meta, workspace } = await fixture(t)
  const support = { name: '验收人', dir: 'AT_验收人' }
  meta.members.push(support)
  await writeFile(path.join(root, 'AT.json'), JSON.stringify(meta))
  for (const stage of stages) await mkdir(path.join(root, support.dir, 'workspace', stage), { recursive: true })
  const file = name => path.join(root, meta.members[0].dir, name)
  const agent = '# 工程师\n\n## 人设\n\n角色说明。'
  await writeFile(file('Agent.md'), agent)
  const task = taskDoc(1)
  await writeFile(path.join(workspace, stages[0], task.id + '.md'), task.raw)
  const store = await registry(config)
  const id = (await store.register(root)).active
  const read = include => snapshot(store.find(id), '', include)
  assert.equal((await read(false)).profiles, undefined)
  const first = await read(true)
  assert.deepEqual(first.profiles.map(p => p.name), ['工程师', '验收人'])
  assert.equal(first.profiles[0].agent.text, agent)
  assert.deepEqual(first.profiles[0].reports, [])
  assert.match(first.profiles[0].memory.error, /未找到 Memory.md/)
  assert.deepEqual(first.tasks.map(t => t.role), ['工程师'])
  await writeFile(file('Memory.md'), '最新进展')
  assert.equal((await read(true)).profiles[0].memory.text, '最新进展')
})

test('原生选择器适配层支持取消、错误及选择；报告端口按相对路径提供文件', async t => {
  const { dir, root, config } = await fixture(t)
  const folders = [null, dir, root]
  const server = await startBoard({ directory: config, port: 0, dist: dir, picker: async () => folders.shift() })
  t.after(() => server.close())
  const post = (suffix, origin = server.url) => fetch(server.url + '/api/projects/' + suffix, {
    method: 'POST', headers: { Origin: origin, 'X-Board-Request': '1' } })
  assert.equal((await post('add', 'http://example.invalid')).status, 403)
  assert.deepEqual(await (await post('add')).json(), { projects: [], active: null })
  assert.equal((await post('add')).status, 400)
  const { active } = await (await post('add')).json()
  const snap = () => fetch(server.url + '/api/projects/' + active + '/snapshot').then(r => r.json())
  assert.deepEqual((await snap()).reports, [])
  const baseDir = path.join(root, 'publish')
  const title = '本地 报告'
  const bundle = path.join(baseDir, title)
  await mkdir(bundle)
  const entry = '<meta http-equiv="refresh" content="0;url=' + encodeURIComponent(title) + '/index.html">'
  await writeFile(path.join(baseDir, title + '.html'), entry)
  await writeFile(path.join(bundle, 'index.html'), '<script src="app.js"></script><a href="子页.html">打开</a>')
  await writeFile(path.join(bundle, 'app.js'), 'document.title="成功"')
  await writeFile(path.join(bundle, '子页.html'), '子页面')
  await writeFile(path.join(baseDir, '独立.htm'), '单页')
  for (const kind of ['dev', 'user', 'bin']) {
    const folder = path.join(baseDir, kind, 'v1.0', 'r2')
    await mkdir(path.join(folder, 'assets'), { recursive: true })
    await writeFile(path.join(folder, 'index.html'), kind)
    await writeFile(path.join(folder, 'assets', '示例.txt'), '修订素材')
  }
  await mkdir(path.join(root, '.at-state'))
  await writeFile(path.join(root, '.at-state', 'releases.json'), JSON.stringify([
    { version: '1.0', entry: 'publish/' + title + '.html' },
    { version: '1.0', entry: 'publish/user/v1.0/r2/index.html' }
  ]))
  const reports = (await snap()).reports
  assert.equal(reports.length, 3)
  assert.ok(!reports.some(r => r.file === '独立.htm'))
  assert.deepEqual(reports.filter(r => r.kind).map(r => r.kind).sort(), ['dev', 'user'])
  for (const item of reports.filter(r => r.kind)) {
    assert.equal(item.version, 'v1.0')
    assert.equal(item.revision, 'r2')
    assert.equal(await (await fetch(item.url)).text(), item.kind)
    assert.equal(await (await fetch(new URL('assets/示例.txt', item.url))).text(), '修订素材')
  }
  assert.ok(reports[0].modified >= reports[1].modified)
  const report = reports.find(r => r.file === title + '.html')
  assert.notEqual(new URL(report.url).origin, server.url)
  assert.equal(await (await fetch(report.url)).text(), entry)
  assert.equal(await (await fetch(new URL(title + '/子页.html', report.url))).text(), '子页面')
  assert.match((await fetch(new URL(title + '/app.js', report.url))).headers.get('Content-Type'), /javascript/)
  assert.equal((await fetch(new URL('/api/projects', report.url))).ok, false)
  await symlink(config, path.join(bundle, 'outside'), 'junction')
  assert.equal((await fetch(new URL(title + '/outside/projects.json', report.url))).ok, false)

  const reportDir = path.join(root, 'AT_工程师', 'report')
  await mkdir(reportDir)
  await writeFile(path.join(reportDir, '进展.html'), '<a href="报告/进展.zip">下载</a>')
  await mkdir(path.join(reportDir, '报告'))
  await writeFile(path.join(reportDir, '报告', '进展.zip'), 'test contents')
  const details = await fetch(server.url + '/api/projects/' + active + '/snapshot?profiles=1').then(r => r.json())
  const [personal] = details.profiles[0].reports
  assert.equal(personal.file, '进展.html')
  assert.equal((await fetch(personal.url)).status, 200)
  assert.equal(await (await fetch(new URL('报告/进展.zip', personal.url))).text(), 'test contents')
  assert.equal((await fetch(new URL('../未登记/进展.html', personal.url))).ok, false)
  await symlink(config, path.join(reportDir, 'outside'), 'junction')
  assert.equal((await fetch(new URL('outside/projects.json', personal.url))).ok, false)
})

