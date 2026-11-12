import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';

const mockAlpineData = mock<(name: string, callback: () => unknown) => void>();
const mockPatch = mock<(url: string, data: Record<string, unknown>) => Promise<unknown>>(() => Promise.resolve({}));
const mockShowError = mock<(message: string) => void>();

mock.module('alpinejs', () => ({ default: { data: mockAlpineData } }));
mock.module('../utils', () => ({ default: { patch: mockPatch } }));
mock.module('../alerts', () => ({ showSuccess: mock(), showError: mockShowError }));

// Imported after the mocks are installed so the real module registers against them.
const { registerReleaseEditor } = await import('./release-editor');

interface Editor {
    form: { name: string; released_at: string; replaces: string; replaces_line: string };
    replacesLocked: boolean;
    openEditModal(release: Record<string, unknown>): void;
    replaceOptions(): { id: string; name: string }[];
    submitRelease(): Promise<void>;
    $dispatch: ReturnType<typeof mock>;
}

interface ReplaceData {
    options: { id: string; name: string }[];
    replaces: Record<string, { id: string; name: string; drop_in: boolean }[]>;
}

// 2.0 replaces 1.9.5 on the same line, so 1.9.5 is not among the monitored options.
const replaceData: ReplaceData = {
    options: [{ id: 'rel-1', name: '2.0' }, { id: 'rel-0', name: '1.8' }],
    replaces: { 'rel-1': [{ id: 'rel-old', name: '1.9.5', drop_in: true }] },
};

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
function open(data?: ReplaceData): Editor {
    mockAlpineData.mockClear();
    registerReleaseEditor();
    const factory = mockAlpineData.mock.calls[0]![1] as unknown as (
        params: { refreshEvent: string; replaceData?: ReplaceData }
    ) => Editor;
    const editor = factory({ refreshEvent: 'refresh-releases', replaceData: data });
    editor.$dispatch = mock(() => undefined);
    editor.openEditModal(release);
    return editor;
}

describe('release editor', () => {
    const originalWindow = globalThis.window;

    beforeEach(() => {
        mockPatch.mockClear();
        mockShowError.mockClear();
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

    test('the dialog opens on the release it replaces and offers it back', () => {
        const editor = open(replaceData);

        expect(editor.form.replaces).toBe('rel-old');
        expect(editor.form.replaces_line).toBe('same');
        expect(editor.replaceOptions()).toEqual([{ id: 'rel-old', name: '1.9.5' }, { id: 'rel-0', name: '1.8' }]);
    });

    test('an edit that leaves the link alone does not send it', async () => {
        const editor = open(replaceData);
        editor.form.name = '2.0 LTS';

        await editor.submitRelease();

        expect(mockPatch.mock.calls[0]![1]).not.toHaveProperty('supersedes');
    });

    test('choosing None detaches the release', async () => {
        const editor = open(replaceData);
        editor.form.replaces = '';

        await editor.submitRelease();

        expect(mockPatch.mock.calls[0]![1].supersedes).toEqual([]);
    });

    test('moving the link to a new line keeps the old release monitored', async () => {
        const editor = open(replaceData);
        editor.form.replaces_line = 'new';

        await editor.submitRelease();

        expect(mockPatch.mock.calls[0]![1].supersedes).toEqual([{ release_id: 'rel-old', drop_in: false }]);
    });

    test('a release chosen without a line is not saved', async () => {
        const editor = open({ ...replaceData, replaces: {} });
        editor.form.replaces = 'rel-0';

        await editor.submitRelease();

        expect(mockPatch).not.toHaveBeenCalled();
        expect(mockShowError.mock.calls[0]![0]).toContain('Same line or New line');
    });

    test('a release that replaces several is left to its own page', async () => {
        const editor = open({
            ...replaceData,
            replaces: { 'rel-1': [{ id: 'a', name: '1.9', drop_in: true }, { id: 'b', name: '1.8', drop_in: false }] },
        });
        expect(editor.replacesLocked).toBe(true);
        editor.form.name = '2.0 LTS';

        await editor.submitRelease();

        expect(mockPatch.mock.calls[0]![1]).not.toHaveProperty('supersedes');
    });
});
