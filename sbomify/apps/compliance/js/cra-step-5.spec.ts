import { describe, test, expect, mock, beforeEach } from 'bun:test';
import { craSharedMock } from './cra-shared.mock';

// No DOM here: the component only touches window.parseJsonScript and window.open.
const win = ((globalThis as unknown as { window?: object }).window ??= {}) as {
  parseJsonScript?: (id: string) => unknown;
  open?: (url: string) => null;
};

mock.module('../../core/js/alpine-components', () => ({
  registerAlpineComponent: () => {},
}));
mock.module('../../core/js/csrf', () => ({
  getCsrfToken: () => 'test-csrf-token',
}));
const errors: string[] = [];
mock.module('../../core/js/alerts', () => ({
  showError: (message: string) => errors.push(message),
  showSuccess: () => {},
}));
mock.module('./cra-shared', () => craSharedMock({ getAssessmentId: () => 'a1' }));

const { craStep5 } = await import('./cra-step-5');

const signedExport = {
  id: 'pkg-1',
  content_hash: 'abc',
  created_at: '2026-10-20T00:00:00Z',
  integrity: {
    hash_algorithm: 'sha256',
    manifest_hash_file: 'metadata/manifest.sha256',
    verification_doc: 'metadata/INTEGRITY.md',
    signature: { algorithm: 'ecdsa-p256-sha256', encoding: 'base64-der', key_id: '0123456789abcdef', public_key_url: 'https://x' },
  },
};

let fetched: string[];
let opened: string[];
let signatureUrls: (string | null)[];

function stubPage(lastExport: unknown): void {
  win.parseJsonScript = (id: string) =>
    id === 'step-data' ? { steps: {}, last_export: lastExport, overall_ready: true, export_available: true } : {};
}

beforeEach(() => {
  fetched = [];
  opened = [];
  errors.length = 0;
  signatureUrls = ['https://s3/sig-1', 'https://s3/sig-2'];
  globalThis.fetch = (async (url: string) => {
    fetched.push(url);
    if (url.endsWith('/download')) {
      return { ok: true, json: async () => ({ download_url: 'https://s3/zip', signature_url: signatureUrls.shift() ?? null }) };
    }
    if (url.endsWith('/export')) {
      return { ok: true, json: async () => ({ id: 'pkg-2' }) };
    }
    return { ok: true, json: async () => ({ data: { documents: {} } }) };
  }) as unknown as typeof fetch;
  win.open = (url: string) => {
    opened.push(url);
    return null;
  };
});

describe('craStep5 signature download', () => {
  test('a saved signed export offers its signature after a reload', () => {
    stubPage(signedExport);
    const c = craStep5();
    c.init();
    expect(c.signedPackageId).toBe('pkg-1');
  });

  test('an unsigned saved export offers no signature', () => {
    stubPage({ ...signedExport, integrity: { ...signedExport.integrity, signature: null } });
    const c = craStep5();
    c.init();
    expect(c.signedPackageId).toBe('');
  });

  test('each click asks for a fresh signature URL', async () => {
    stubPage(signedExport);
    const c = craStep5();
    c.init();
    await c.downloadSignature();
    await c.downloadSignature();
    expect(fetched.filter((u) => u === '/api/v1/compliance/cra/a1/export/pkg-1/download')).toHaveLength(2);
    expect(opened).toEqual(['https://s3/sig-1', 'https://s3/sig-2']);
  });

  test('a fresh export offers its own signature', async () => {
    stubPage(null);
    const c = craStep5();
    c.init();
    await c.exportBundle();
    expect(c.signedPackageId).toBe('pkg-2');
  });

  test('an export that came back unsigned offers none', async () => {
    stubPage(signedExport);
    signatureUrls = [null];
    const c = craStep5();
    c.init();
    await c.exportBundle();
    expect(c.signedPackageId).toBe('');
  });
});
