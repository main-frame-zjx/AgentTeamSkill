import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import path from 'node:path'

const [major, minor] = process.versions.node.split('.').map(Number)
if (major < 22 || (major === 22 && minor < 12)) throw new Error('请安装 Node.js 22.12 或更新版本')
const url = 'http://127.0.0.1:47361'
const prepareOnly = process.argv.includes('--prepare-only')
const running = !prepareOnly && await fetch(url + '/api/health', { signal: AbortSignal.timeout(1000) })
  .then(r => r.json()).catch(() => null)
function run(command) {
  const result = spawnSync(process.env.ComSpec || 'cmd.exe', ['/d', '/c', command], { stdio: 'inherit' })
  if (result.status !== 0) process.exit(result.status || 1)
}
if (running?.app !== 'agent-team-board') {
  const fingerprint = createHash('sha256').update(readFileSync('package-lock.json')).digest('hex')
  const saved = file => existsSync(file) ? readFileSync(file, 'utf8') : ''
  if (saved('node_modules/.board-lock') !== fingerprint) {
    run('npm.cmd ci --include=dev --no-audit --no-fund')
    writeFileSync('node_modules/.board-lock', fingerprint)
  }
  const inputs = readdirSync('src', { recursive: true, withFileTypes: true })
    .filter(item => item.isFile()).map(item => path.join(item.parentPath, item.name))
  const hash = createHash('sha256').update(fingerprint)
  for (const file of [...inputs.sort(), 'index.html', 'package.json', 'tsconfig.json', 'vite.config.ts']) {
    hash.update(file).update(readFileSync(file))
  }
  const build = hash.digest('hex')
  if (!existsSync('dist/index.html') || saved('dist/.board-build') !== build) {
    run('npm.cmd run build')
    writeFileSync('dist/.board-build', build)
  }
}
if (!prepareOnly) run('node server/start.mjs --open')

