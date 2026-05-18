import { describe, test, expect, mock } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Regression coverage for the DoC signature pad zoom-on-reload bug.
 *
 * Two layers:
 *
 * 1. **Unit tests** for the ratio formula. ``_fitCanvas`` pre-scales the
 *    canvas back-buffer by ``window.devicePixelRatio`` and applies
 *    ``ctx.scale(ratio, ratio)`` — the restore path must pass the SAME
 *    ratio to ``SignaturePad.fromDataURL`` or the saved PNG renders
 *    zoomed in 2× on retina screens.
 *
 * 2. **Source-text guard** on ``cra-doc-signature.ts`` so the actual
 *    call site can't silently regress back to ``{ ratio: 1 }``. Bun's
 *    test runner doesn't have a DOM and the production factory pulls in
 *    Alpine.js (which needs ``MutationObserver``), so a full integration
 *    test would need a heavy jsdom/happy-dom setup. The source check is
 *    the pragmatic alternative: it fires the moment anyone reverts the
 *    one-line fix, with zero runtime dependencies.
 */

const computeRatio = (devicePixelRatio: number | undefined): number =>
  Math.max(devicePixelRatio || 1, 1);

describe('CRA DoC signature pad restore ratio (unit)', () => {
  test('matches the fitted-canvas ratio formula for retina screens', () => {
    expect(computeRatio(2)).toBe(2);
    expect(computeRatio(3)).toBe(3);
    expect(computeRatio(1.5)).toBe(1.5);
  });

  test('falls back to 1 for non-retina and missing devicePixelRatio', () => {
    expect(computeRatio(1)).toBe(1);
    expect(computeRatio(undefined)).toBe(1);
    expect(computeRatio(0)).toBe(1);
  });

  test('never drops below 1 even with sub-pixel ratios', () => {
    expect(computeRatio(0.5)).toBe(1);
    expect(computeRatio(0.75)).toBe(1);
  });

  test('regression: ratio:1 hardcoding (the original bug) mismatches on retina', () => {
    const fitRatio = computeRatio(2);
    const buggyRestoreRatio = 1;
    expect(fitRatio).not.toBe(buggyRestoreRatio);
  });

  test('restore options shape passes ratio to signature_pad', () => {
    const fromDataURL = mock((_data: string, _options: { ratio: number }) => {});
    const ratio = computeRatio(2);
    fromDataURL('data:image/png;base64,...', { ratio });

    expect(fromDataURL).toHaveBeenCalledTimes(1);
    const call = fromDataURL.mock.calls[0];
    expect(call[1]).toHaveProperty('ratio', ratio);
  });
});

describe('CRA DoC signature pad restore ratio (source guard)', () => {
  // Reads cra-doc-signature.ts and asserts the actual restore call uses
  // the devicePixelRatio formula. Catches reverts to ``{ ratio: 1 }`` —
  // i.e. exactly the bug this PR fixes — even though the test runner
  // can't execute the Alpine + signature_pad stack.
  const source = readFileSync(join(import.meta.dir, 'cra-doc-signature.ts'), 'utf8');

  test('the restore call uses Math.max(window.devicePixelRatio || 1, 1)', () => {
    expect(source).toContain('Math.max(window.devicePixelRatio || 1, 1)');
  });

  test('the restore call does NOT hardcode ratio: 1 (the original bug)', () => {
    // Match any ``fromDataURL(..., { ratio: 1 })`` literal. Multi-line
    // safe because we collapse whitespace in the test pattern.
    const collapsed = source.replace(/\s+/g, ' ');
    expect(collapsed).not.toMatch(/fromDataURL\([^)]*\{\s*ratio:\s*1\s*\}/);
  });

  test('the restore call invokes fromDataURL with a ratio option', () => {
    const collapsed = source.replace(/\s+/g, ' ');
    expect(collapsed).toMatch(/this\.pad\.fromDataURL\([^)]*\{\s*ratio\s*\}/);
  });
});
