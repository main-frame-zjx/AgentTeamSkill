import http from 'node:http'
import path from 'node:path'
import { stat } from 'node:fs/promises'
import { createReadStream } from 'node:fs'
import { pipeline } from 'node:stream/promises'
import mime from 'mime-types'
import { manifest, releaseRevision, resolveInside, roleReportRoot, snapshot } from './project.mjs'
import { registry } from './registry.mjs'
import { pickFolder } from './picker.mjs'

const ip = '127.0.0.1'
const base = server => 'http://' + ip + ':' + server.address().port

function json(res, value, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
  res.end(JSON.stringify(value))
}

function localServer(handler) {
  const server = http.createServer(async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff')
    res.setHeader('Referrer-Policy', 'no-referrer')
    try {
      if (req.headers.host !== ip + ':' + server.address().port) return json(res, { error: '无效的主机' }, 403)
      const pathname = req.url.split('?')[0]
      const parts = pathname.slice(1).split('/').map(decodeURIComponent)
      if (!pathname.startsWith('/') || parts.some(p => p === '.' || p === '..' || /[\\/:*\x00-\x1f]/.test(p))) {
        return json(res, { error: '路径无效' }, 400)
      }
      await handler(req, res, pathname, parts)
    } catch (error) {
      if (!res.headersSent) json(res, { error: error.message }, error.code === 'ENOENT' ? 404 : 400)
      else res.destroy()
    }
  })
  return server
}

async function serveFile(req, res, root, parts) {
  if (!['GET', 'HEAD'].includes(req.method)) return json(res, { error: '方法无效' }, 405)
  const file = await resolveInside(root, ...parts)
  const info = await stat(file)
  if (!info.isFile()) return json(res, { error: '文件不存在' }, 404)
  res.writeHead(200, { 'Content-Type': mime.contentType(path.extname(file)) || 'application/octet-stream',
    'Content-Length': info.size, 'Cache-Control': 'no-cache' })
  if (req.method === 'HEAD') res.end()
  else await pipeline(createReadStream(file), res)
}

function listen(server, port) {
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, ip, () => { server.off('error', reject); resolve() })
  })
}

function close(server) {
  return new Promise(resolve => {
    server.close(resolve)
    server.closeAllConnections()
  })
}

export async function startBoard({ directory, dist, port, picker = pickFolder }) {
  const store = await registry(directory)
  let picking = false
  const reports = localServer(async (req, res, pathname, parts) => {
    const scope = parts.shift()
    let root
    if (scope === 'role') {
      const project = store.find(parts.shift())
      const directory = parts.shift()
      const data = await manifest(project.root)
      if (data.id !== project.manifestId || !data.members.some(member => member.dir === directory)) {
        return json(res, { error: '角色不属于登记项目' }, 404)
      }
      root = await roleReportRoot(project.root, directory)
    } else {
      const project = store.find(scope)
      if ((await manifest(project.root)).id !== project.manifestId || !releaseRevision(...parts.slice(0, 3))) {
        return json(res, { error: '发布修订不存在' }, 404)
      }
      const publicRoot = await resolveInside(project.root, 'publish')
      const revision = parts.splice(0, 3)
      root = await resolveInside(publicRoot, ...revision)
      if (path.relative(path.resolve(publicRoot, ...revision), root)) {
        return json(res, { error: '发布修订目录已重定向' }, 404)
      }
    }
    if (!parts.length || parts.at(-1) === '') parts.push('index.html')
    return serveFile(req, res, root, parts)
  })
  const board = localServer(async (req, res, pathname, parts) => {
    if (pathname === '/api/health' && req.method === 'GET') return json(res, { app: 'agent-team-board', version: 1 })
    if (pathname === '/api/projects' && req.method === 'GET') return json(res, store.state())
    if (parts[0] === 'api' && parts[1] === 'projects') {
      const [, , id, action] = parts
      if (req.method === 'GET' && parts.length === 4 && action === 'snapshot') {
        const withProfiles = new URL(req.url, base(board)).searchParams.get('profiles') === '1'
        return json(res, await snapshot(store.find(id), base(reports), withProfiles))
      }
      if (req.method !== 'POST') return json(res, { error: '操作无效' }, 405)
      if (req.headers.origin !== base(board) || req.headers['x-board-request'] !== '1') {
        return json(res, { error: '请从本机看板发起操作' }, 403)
      }
      if ((parts.length === 3 && id === 'add') || (parts.length === 4 && action === 'relocate')) {
        if (picking) return json(res, { error: '请先完成已打开的文件夹选择' }, 409)
        if (action) store.find(id)
        picking = true
        try {
          const folder = await picker()
          return json(res, folder ? await store.register(folder, action ? id : null) : store.state())
        } finally {
          picking = false
        }
      }
      if (parts.length === 4 && action === 'select') return json(res, await store.select(id))
      if (parts.length === 4 && action === 'remove') return json(res, await store.remove(id))
    }
    if (parts[0] === 'api') return json(res, { error: '接口不存在' }, 404)
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
    return serveFile(req, res, dist, pathname === '/' ? ['index.html'] : parts)
  })
  await listen(reports, 0)
  try {
    await listen(board, port)
  } catch (error) {
    await close(reports)
    throw error
  }
  return { url: base(board), close: () => Promise.all([close(board), close(reports)]) }
}

