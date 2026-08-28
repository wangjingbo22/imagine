import { mkdir, readdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'

const testDir = new URL('../tests/', import.meta.url)
const rolldownCli = join(process.cwd(), 'node_modules', 'rolldown', 'bin', 'cli.mjs')
const outputDir = join(process.cwd(), '.test-dist')
await rm(outputDir, { recursive: true, force: true })
await mkdir(outputDir)
const bundledTests = []
try {
  const tests = (await readdir(testDir)).filter((file) => file.endsWith('.test.ts'))
  for (const test of tests) {
    const bundled = join(outputDir, test.replace(/\.ts$/, '.mjs'))
    const bundle = spawnSync(process.execPath, [rolldownCli, join('tests', test), '--file', bundled, '--format', 'esm', '--platform', 'node'], { stdio: 'inherit' })
    if (bundle.status !== 0) process.exitCode = bundle.status ?? 1
    bundledTests.push(bundled)
  }
  if (!process.exitCode) {
    const run = spawnSync(process.execPath, ['--test', ...bundledTests], { stdio: 'inherit' })
    process.exitCode = run.status ?? 1
  }
} finally {
  await rm(outputDir, { recursive: true, force: true })
}
