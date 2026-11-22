// Isolated official Harness registry/provider for the uninstall integration test.
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import path from 'node:path'
import readline from 'node:readline/promises'

const [modules, workspace, userRoot, projectRoot, bridge] = process.argv.slice(2)
const resolve = createRequire(path.resolve(modules, '../package.json')).resolve
const load = pkg => import(pathToFileURL(resolve('@deepseek-ai/' + pkg)))
const { Context } = await load('cordis')
const { default: Registry } = await load('dsh-skill')
const provider = await load('dsh-skill-filesystem')
const { observe } = await import(pathToFileURL(bridge))
const ctx = new Context()
await ctx.plugin(Registry)
await ctx.plugin(provider, { includeDefaultRoots: false, customSkillDirs: [projectRoot, userRoot],
  watch: true, watchStabilityThresholdMs: 50 })
const agent = {}
// Supply the workspace service the same way the calling tool resolves its own cwd.
ctx.workingDirectory = { ensure: () => workspace }
for await (const challenge of readline.createInterface({ input: process.stdin })) {
  const view = await observe(ctx, agent, 'uninstall-test', challenge)
  process.stdout.write(JSON.stringify(view) + '\n')
}
process.exit(0)
