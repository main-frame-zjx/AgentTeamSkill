import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { startBoard } from './http.mjs'

const portOption = process.argv.indexOf('--port')
const port = portOption < 0 ? 47361 : Number(process.argv[portOption + 1])
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('看板端口无效')
const url = 'http://127.0.0.1:' + port
const openBrowser = process.argv.includes('--open')
let service
try {
  service = await startBoard({
    directory: path.join(process.env.LOCALAPPDATA, 'AgentTeamBoard'),
    dist: fileURLToPath(new URL('../dist/', import.meta.url)), port
  })
} catch (error) {
  if (error.code !== 'EADDRINUSE') throw error
  const health = await fetch(url + '/api/health', { signal: AbortSignal.timeout(2000) })
    .then(r => r.json()).catch(() => null)
  if (health?.app !== 'agent-team-board') throw new Error(`端口 ${port} 已被其他程序占用`)
}
console.log(service ? 'Agent Team Board 已启动：' + url + '\n关闭此窗口或按 Ctrl+C 停止服务。' : '正在使用已启动的看板：' + url)
if (openBrowser) {
  const child = spawn('rundll32.exe', ['url.dll,FileProtocolHandler', url], { detached: true, stdio: 'ignore', windowsHide: true })
  child.unref()
}
if (service) {
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => service.close())
}

