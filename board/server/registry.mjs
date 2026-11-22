import { randomUUID } from 'node:crypto'
import { mkdir, readFile, realpath, rename, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { manifest } from './project.mjs'

export async function registry(directory) {
  const file = path.join(directory, 'projects.json')
  let state = { projects: [], active: null }
  try {
    const saved = JSON.parse(await readFile(file, 'utf8'))
    if (!Array.isArray(saved.projects) || !saved.projects.every(p => p.id && p.manifestId && p.name && path.isAbsolute(p.root))
        || (saved.active !== null && !saved.projects.some(p => p.id === saved.active))) {
      throw new Error('项目列表格式错误')
    }
    state = saved
  } catch (error) {
    if (error.code !== 'ENOENT') throw new Error(file + ' 无法读取：' + error.message)
  }
  let queue = Promise.resolve()
  function change(action) {
    const result = queue.then(async () => {
      const next = structuredClone(state)
      await action(next)
      await mkdir(directory, { recursive: true })
      const temp = file + '.' + randomUUID() + '.tmp'
      try {
        await writeFile(temp, JSON.stringify(next, null, 2) + '\n')
        await rename(temp, file)
      } finally {
        await rm(temp, { force: true })
      }
      state = next
      return next
    })
    queue = result.catch(() => {})
    return result
  }
  function find(id, inState = state) {
    const entry = inState.projects.find(p => p.id === id)
    if (!entry) throw new Error('项目未登记')
    return entry
  }
  return {
    state: () => state, find,
    async register(folder, relocate) {
      const root = await realpath(folder)
      const data = await manifest(root)
      return change(next => {
        const existing = next.projects.find(p => path.relative(p.root, root) === '')
        if (relocate) {
          const project = find(relocate, next)
          if (project.manifestId !== data.id) throw new Error('所选文件夹与原项目的 AT.json 标识不同')
          if (existing && existing.id !== relocate) throw new Error('此路径已在项目列表中')
          Object.assign(project, { root, name: data.name })
          next.active = project.id
        } else {
          const project = existing ?? { id: randomUUID(), root }
          Object.assign(project, { manifestId: data.id, name: data.name })
          if (!existing) next.projects.push(project)
          next.active = project.id
        }
      })
    },
    select: id => change(next => { next.active = find(id, next).id }),
    remove: id => change(next => {
      find(id, next)
      next.projects = next.projects.filter(p => p.id !== id)
      if (next.active === id) next.active = next.projects[0]?.id ?? null
    })
  }
}

