import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>();
const mockPatch = mock<(url: string, data: Record<string, unknown>) => Promise<unknown>>(() => Promise.resolve({}));

mock.module('alpinejs', () => ({ default: { data: mockAlpineData } }));
mock.module('../utils', () => ({ default: { patch: mockPatch } }));
mock.module('../alerts', () => ({ showSuccess: mock(), showError: mock() }));

// Imported after the mocks are installed so the real module registers against them.
const { registerReleaseEditor } = await import('./release-editor');

interface Editor {
    form: { name: string; released_at: string };
    openEditModal(release: Record<string, unknown>): void;
    submitRelease(): Promise<void>;
    $dispatch: ReturnType<typeof mock>;
}

const release = {
    id: 'rel-1',
    name: '2.0',
    version: '2.0',
    is_prerelease: false,
    is_latest: false,
    created_at: '2025-01-01T00:00:00Z',
    release_date: '2025-03-01T12:00:45.500Z',
};

/** Builds the real Alpine component and opens the dialog on the release above. */
function open(): Editor {
    mockAlpineData.mockClear();
    registerReleaseEditor();
    const factory = mockAlpineData.mock.calls[0]![1] as unknown as (params: { refreshEvent: string }) => Editor;
    const editor = factory({ refreshEvent: 'refresh-releases' });
    editor.$dispatch = mock(() => undefined);
    editor.openEditModal(release);
    return editor;
}

describe('release editor', () => {
    const originalWindow = globalThis.window;

    beforeEach(() => {
        mockPatch.mockClear();
        globalThis.window = { dispatchEvent: () => true } as unknown as Window & typeof globalThis;
    });

    afterEach(() => {
        globalThis.window = originalWindow;
    });

    test('an edit that leaves the release date alone does not send it', async () => {
        const editor = open();
        editor.form.name = '2.0 LTS';

        await editor.submitRelease();

        const [url, data] = mockPatch.mock.calls[0]!;
        expect(url).toBe('/api/v1/releases/rel-1');
        expect(data.name).toBe('2.0 LTS');
        expect(data).not.toHaveProperty('released_at');
    });

    test('a release date the user changed is sent', async () => {
        const editor = open();
        editor.form.released_at = '2025-04-01T09:30';

        await editor.submitRelease();

        expect(mockPatch.mock.calls[0]![1].released_at).toBe(new Date('2025-04-01T09:30').toISOString());
    });
});
