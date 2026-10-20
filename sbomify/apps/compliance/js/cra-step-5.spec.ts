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
const successes: string[] = [];
mock.module('../../core/js/alerts', () => ({
  showError: (message: string) => errors.push(message),
  showSuccess: (message: string) => successes.push(message),
}));
mock.module('./cra-shared', () => craSharedMock({ getAssessmentId: () => 'a1' }));

const { craStep5 } = await import('./cra-step-5');

const signature = {
  signed_by: 'security@acme.test',
  issuer: 'https://accounts.google.com',
  signed_at: '2026-08-06T01:03:01+00:00',
};
const unsignedExport = {
  id: 'pkg-1',
  content_hash: 'abc',
  created_at: '2026-10-20T00:00:00Z',
  file_name: 'cra-package-acme-abc.zip',
  signature: null,
};

interface Call {
  url: string;
  init?: RequestInit;
}
let calls: Call[];
let opened: string[];
let signatureUrls: (string | null)[];
let signResponse: { ok: boolean; status: number; body: unknown };

function stubPage(lastExport: unknown): void {
  win.parseJsonScript = (id: string) =>
    id === 'step-data' ? { steps: {}, last_export: lastExport, overall_ready: true, export_available: true } : {};
}

function bundleFile(text: string): File {
  return { name: 'cra-package-acme-abc.zip.sigstore.json', text: async () => text } as unknown as File;
}

beforeEach(() => {
  calls = [];
  opened = [];
  errors.length = 0;
  successes.length = 0;
  signatureUrls = ['https://s3/sig-1', 'https://s3/sig-2'];
  signResponse = { ok: true, status: 201, body: signature };
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith('/download')) {
      return { ok: true, json: async () => ({ download_url: 'https://s3/zip', signature_url: signatureUrls.shift() ?? null }) };
    }
    if (url.endsWith('/signature')) {
      return { ok: signResponse.ok, status: signResponse.status, json: async () => signResponse.body };
    }
    return { ok: true, json: async () => ({ data: { documents: {} } }) };
  }) as unknown as typeof fetch;
  win.open = (url: string) => {
    opened.push(url);
    return null;
  };
});

describe('craStep5 signing commands', () => {
  test('name the exported file', () => {
    stubPage(unsignedExport);
    const c = craStep5();
    c.init();
    expect(c.signCommand).toBe(
      'cosign sign-blob cra-package-acme-abc.zip --bundle cra-package-acme-abc.zip.sigstore.json',
    );
  });

  test('verification names the signer and issuer once signed', () => {
    stubPage({ ...unsignedExport, signature });
    const c = craStep5();
    c.init();
    expect(c.verifyCommand).toBe(
      'cosign verify-blob cra-package-acme-abc.zip --bundle cra-package-acme-abc.zip.sigstore.json' +
        ' --certificate-identity security@acme.test --certificate-oidc-issuer https://accounts.google.com',
    );
    expect(c.issuerLabel(signature.issuer)).toBe('Google');
    expect(c.issuerLabel('https://gitlab.example.test')).toBe('https://gitlab.example.test');
  });
});

describe('craStep5 signature upload', () => {
  test('sends the bundle with the signer, and shows who signed', async () => {
    stubPage(unsignedExport);
    const c = craStep5();
    c.init();
    c.signFile = bundleFile('{"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}');
    c.signForm.identity = ' security@acme.test ';
    c.signForm.issuer = 'https://accounts.google.com';

    await c.uploadSignature();

    const call = calls.find((x) => x.url === '/api/v1/compliance/cra/a1/export/pkg-1/signature');
    expect(call?.init?.method).toBe('POST');
    expect(JSON.parse(call?.init?.body as string)).toEqual({
      bundle: { mediaType: 'application/vnd.dev.sigstore.bundle.v0.3+json' },
      identity: 'security@acme.test',
      issuer: 'https://accounts.google.com',
    });
    expect(c.lastExport?.signature).toEqual(signature);
    expect(errors).toEqual([]);
  });

  test('a file that is not JSON is refused before anything is sent', async () => {
    stubPage(unsignedExport);
    const c = craStep5();
    c.init();
    c.signFile = bundleFile('not json');
    c.signForm.identity = 'security@acme.test';

    await c.uploadSignature();

    expect(calls.some((x) => x.url.endsWith('/signature'))).toBe(false);
    expect(errors).toEqual(['This file is not a Sigstore bundle.']);
  });

  test("the server's reason is shown when it refuses", async () => {
    stubPage(unsignedExport);
    signResponse = { ok: false, status: 400, body: { error: 'The signature does not match this bundle.' } };
    const c = craStep5();
    c.init();
    c.signFile = bundleFile('{}');
    c.signForm.identity = 'security@acme.test';

    await c.uploadSignature();

    expect(errors).toEqual(['The signature does not match this bundle.']);
    expect(c.lastExport?.signature).toBeNull();
    expect(c.isSigning).toBe(false);
  });
});

describe('craStep5 signature download', () => {
  test('each click asks for a fresh signature URL', async () => {
    stubPage({ ...unsignedExport, signature });
    const c = craStep5();
    c.init();
    await c.downloadSignature();
    await c.downloadSignature();
    expect(calls.filter((x) => x.url === '/api/v1/compliance/cra/a1/export/pkg-1/download')).toHaveLength(2);
    expect(opened).toEqual(['https://s3/sig-1', 'https://s3/sig-2']);
  });

  test('an unsigned export offers nothing to download', async () => {
    stubPage(unsignedExport);
    const c = craStep5();
    c.init();
    await c.downloadSignature();
    expect(calls.some((x) => x.url.endsWith('/download'))).toBe(false);
  });
});
