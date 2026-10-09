import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from 'vitest'

const script: string = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../scripts/sandbox/generate-e2e-matrix.mjs')
const TAGS: string = JSON.stringify([{ ref: 'v2026.6.19', desktop: true }])

interface Leg {
  name: string
}
type Matrices = Record<'linux' | 'windows' | 'macos', { include: Leg[] }>

function generate(route: string): Matrices {
  return JSON.parse(execFileSync(process.execPath, [script, '--tags', TAGS, '--route', route], { encoding: 'utf8' })) as Matrices
}

function legNames(matrices: Matrices): string[] {
  return Object.values(matrices).flatMap(m => m.include.map(leg => leg.name))
}

test('a leg name, or the job name GitHub shows for it, runs exactly that leg', () => {
  const leg: Leg | undefined = generate('all').windows.include.find(l =>
    l.name.includes('installer-script+desktop -> desktop-installer@latest')
  )

  expect(leg).toBeDefined()
  expect(legNames(generate(leg!.name))).toEqual([leg!.name])
  expect(legNames(generate(`${leg!.name} / e2e`))).toEqual([leg!.name])
})

test('an OS preset runs that OS whole and no other', () => {
  const all: Matrices = generate('all')
  const windows: Matrices = generate('windows-desktop')

  expect(legNames(windows)).toEqual(all.windows.include.map(l => l.name))
  expect(windows.linux.include).toEqual([])
  expect(windows.macos.include).toEqual([])
})

test('a route that selects nothing fails instead of running an empty green matrix', () => {
  expect(() => generate('windows: no-such-method')).toThrow()
})

test('a fork without stable releases still exercises HEAD -> NEXT on every OS', () => {
  const matrices: Matrices = JSON.parse(execFileSync(process.execPath, [script, '--tags', '[]'], { encoding: 'utf8' }))

  for (const matrix of Object.values(matrices)) {
    expect(matrix.include.length).toBeGreaterThan(0)
    expect(matrix.include.every(leg => leg.name.includes('(HEAD -> NEXT)'))).toBe(true)
  }
})

test('results survive a failed picker with no tag output', () => {
  const report = execFileSync(process.execPath, [script, '--format', 'results', '--tags', ''], {
    encoding: 'utf8',
    input: JSON.stringify({ name: 'Pick release tags', conclusion: 'failure' }) + '\n',
  })

  expect(report).toContain('Install')
})

test('the pr route runs one script install updated by hermes update per OS start, nothing else', () => {
  const pr: Matrices = generate('pr')

  expect(legNames(pr).sort()).toEqual([
    'linux: installer-script -> hermes-update (HEAD -> NEXT)',
    'linux: installer-script -> hermes-update (v2026.6.19 -> HEAD)',
    'macos: installer-script -> hermes-update (v2026.6.19 -> HEAD)',
    'windows: installer-script -> hermes-update (HEAD -> NEXT)',
  ])
})
