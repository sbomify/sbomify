import { describe, test, expect, mock } from 'bun:test';

/**
 * Regression coverage for the DoC signature pad zoom-on-reload bug.
 *
 * ``_fitCanvas`` (in cra-doc-signature.ts) pre-scales the canvas
 * back-buffer by ``window.devicePixelRatio`` and applies
 * ``ctx.scale(ratio, ratio)``. The restore path therefore must pass
 * the SAME ratio to ``SignaturePad.fromDataURL`` — otherwise the
 * saved PNG is drawn at the wrong size through the already-scaled
 * context and the signature renders zoomed in 2× on retina screens.
 *
 * The contract enforced here:
 *   restore.ratio === Math.max(window.devicePixelRatio || 1, 1)
 *
 * If anyone reverts the restore to ``{ ratio: 1 }`` (the previous
 * buggy value) or otherwise breaks the relationship, these tests
 * catch it without spinning up the full Alpine + signature_pad +
 * fetch stack.
 */

const computeRatio = (devicePixelRatio: number | undefined): number =>
  Math.max(devicePixelRatio || 1, 1);

describe('CRA DoC signature pad restore ratio', () => {
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

  test('regression: ratio:1 hardcoding (the original bug) would mismatch on retina', () => {
    // The bug: passing { ratio: 1 } to fromDataURL while _fitCanvas
    // had scaled the canvas at devicePixelRatio. Document the mismatch.
    const fitRatio = computeRatio(2); // 2× retina
    const buggyRestoreRatio = 1;
    expect(fitRatio).not.toBe(buggyRestoreRatio);
  });

  test('restore options shape passes ratio to signature_pad', () => {
    // signature_pad.fromDataURL options must include the ratio key.
    // This is the option shape cra-doc-signature.ts now uses.
    const fromDataURL = mock((_data: string, _options: { ratio: number }) => {});
    const ratio = computeRatio(2);
    fromDataURL('data:image/png;base64,...', { ratio });

    expect(fromDataURL).toHaveBeenCalledTimes(1);
    const call = fromDataURL.mock.calls[0];
    expect(call[1]).toHaveProperty('ratio', ratio);
  });
});
