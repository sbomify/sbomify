import { afterEach, describe, expect, mock, test } from 'bun:test';
import { repositorySetup } from './repository-setup';

const originalFetch = globalThis.fetch;
const originalDocument = globalThis.document;
afterEach(() => {
    globalThis.fetch = originalFetch;
    globalThis.document = originalDocument;
});

const config = {
    baseUrl: 'http://localhost:8000',
    instructionsUrl: 'http://localhost:8000/setup.md',
    tokenUrl: '/workspaces/example/setup-token/',
};

describe('repository setup', () => {
    test('prompt and commands follow selections and the current instance', () => {
        const setup = repositorySetup(config);
        expect(setup.method).toBe('agent');
        expect(setup.agentPrompt).toContain('Create everything as private.');
        expect(setup.agentPrompt).toContain('http://localhost:8000/api/v1');
        setup.visibility = 'public';
        setup.token = 'test-value';
        expect(setup.agentPrompt).toContain('Create everything as public.');
        expect(setup.agentPrompt).toContain('Bearer test-value');
        expect(setup.command).toContain('-v "$(pwd):/workspace"');
        expect(setup.command).toContain("--api-base-url 'http://host.docker.internal:8000'");
        setup.runtime = 'uv';
        expect(setup.command).toContain("SBOMIFY_TOKEN='test-value' uvx sbomify-action wizard");
        expect(setup.command).toContain("--api-base-url 'http://localhost:8000'");
    });

    test('shell arguments remain quoted', () => {
        const setup = repositorySetup(config);
        setup.token = "a'b$(touch nope)";
        expect(setup.command).toContain("'a'\"'\"'b$(touch nope)'");
    });

    test('creating and resetting are explicit, with no duplicate concurrent request', async () => {
        globalThis.document = { querySelector: () => ({ getAttribute: () => 'csrf' }) } as unknown as Document;
        let complete!: (response: Response) => void;
        const fetcher = mock(() => new Promise<Response>(resolve => { complete = resolve; }));
        globalThis.fetch = fetcher as unknown as typeof fetch;
        const setup = repositorySetup(config);
        expect(fetcher).not.toHaveBeenCalled();
        const pending = setup.mint();
        await setup.mint();
        expect(fetcher).toHaveBeenCalledTimes(1);
        complete(Response.json({ id: 10, token: 'first', expires_at: '2026-10-01T00:00:00Z' }));
        await pending;
        expect(setup.token).toBe('first');
        const reset = mock(async (_url: string, options: RequestInit) => {
            expect(String(options.body)).toBe('previous_id=10');
            return Response.json({ id: 11, token: 'second', expires_at: '2026-10-01T00:00:00Z' });
        });
        globalThis.fetch = reset as unknown as typeof fetch;
        await setup.mint();
        expect(setup.token).toBe('second');
        expect(setup.agentPrompt).not.toContain('Bearer first');
    });

    test('a failed reset preserves the current command and exposes an error', async () => {
        globalThis.document = { querySelector: () => ({ getAttribute: () => 'csrf' }) } as unknown as Document;
        globalThis.fetch = mock(async () => new Response('', { status: 403 })) as unknown as typeof fetch;
        const setup = repositorySetup(config);
        setup.token = 'existing';
        setup.tokenId = 10;
        await setup.mint();
        expect(setup.error).toContain('Could not create');
        expect(setup.token).toBe('existing');
        expect(setup.minting).toBe(false);
    });
});
