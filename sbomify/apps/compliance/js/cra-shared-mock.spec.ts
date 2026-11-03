import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { craSharedMock } from './cra-shared.mock';

describe('craSharedMock', () => {
  test('stands in for every export of cra-shared', () => {
    // Read the source, not the module: another spec may already have mocked it.
    const source = readFileSync(join(import.meta.dir, 'cra-shared.ts'), 'utf8');
    const exported = [...source.matchAll(/^export (?:async )?(?:function|const|let|class) (\w+)/gm)].map((m) => m[1]);
    expect(exported.length).toBeGreaterThan(0);
    expect(Object.keys(craSharedMock()).sort()).toEqual(exported.sort());
  });
});
