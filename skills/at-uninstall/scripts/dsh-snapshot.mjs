// Run inside the original Harness host, with the calling agent as the registry scope.
export async function observe(ctx, agent, session, challenge, signal) {
  if (!agent || !session || !challenge) throw new Error('Missing calling agent, session or challenge')
  const cwd = await ctx.workingDirectory.ensure(agent, signal)
  const { skills, complete } = await ctx.skills.snapshot({ cwd, scope: agent, signal })
  return { host: 'dsh', session, cwd, challenge, complete,
    skills: skills.map(({ name, path, source, provider }) => ({ name, path, source, provider })) }
}
