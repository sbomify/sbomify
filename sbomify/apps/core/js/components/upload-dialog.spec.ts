import { afterAll, afterEach, describe, expect, test } from 'bun:test';
import {
    bomTypeFromDetail,
    bomTypeFromHash,
    resolveRequestedBomType,
    uploadDialog,
    type UploadBomType,
    type UploadRequest,
    type UploadTypeState,
} from './upload-dialog';

// bun runs these without a DOM; the dialog only reads location.hash.
const page = globalThis as { window?: { location: { hash: string } } };
const ownWindow = !page.window;
page.window ??= { location: { hash: '' } };
const setHash = (hash: string) => { page.window!.location.hash = hash; };
afterEach(() => setHash(''));
afterAll(() => { if (ownWindow) delete page.window; });

const openEvent = (detail?: unknown) => ({ detail }) as unknown as Event;

function dialog(hash = '', options?: Parameters<typeof uploadDialog>[0]) {
    setHash(hash);
    const instance = uploadDialog(options);
    instance.init();
    return instance;
}

const idle = (bomType: UploadBomType = 'sbom'): UploadTypeState => ({
    bomType,
    isUploading: false,
    isPreviewing: false,
    preview: null,
});
const request = (bomType: UploadBomType | null, seq = 1): UploadRequest => ({ bomType, seq });

describe('reading a request', () => {
    test('typed hashes name their type, the generic hash asks for the default', () => {
        expect(bomTypeFromHash('#upload-sbom')).toBe('sbom');
        expect(bomTypeFromHash('#upload-cbom')).toBe('cbom');
        expect(bomTypeFromHash('#upload-vex')).toBe('vex');
        expect(bomTypeFromHash('#upload-artifact')).toBeNull();
    });

    test('any other hash is not an upload link', () => {
        for (const hash of ['', '#', '#upload-', '#upload-aibom', '#upload-document', '#vulnerabilities']) {
            expect(bomTypeFromHash(hash)).toBeUndefined();
        }
    });

    test('an event names its type, or asks for the default', () => {
        expect(bomTypeFromDetail({ bomType: 'vex' })).toBe('vex');
        expect(bomTypeFromDetail({ bomType: 'cbom' })).toBe('cbom');
        expect(bomTypeFromDetail(undefined)).toBeNull();
        expect(bomTypeFromDetail(null)).toBeNull();
        expect(bomTypeFromDetail({})).toBeNull();
        expect(bomTypeFromDetail({ bomType: 'aibom' })).toBeNull();
        expect(bomTypeFromDetail({ bomType: 42 })).toBeNull();
    });
});

describe('the BOM uploader', () => {
    test('stays closed with no upload hash', () => {
        const instance = dialog('#vulnerabilities');
        expect(instance.uploadOpen).toBe(false);
        expect(instance.uploadRequest).toBeNull();
    });

    test.each(['sbom', 'cbom', 'vex'] as const)('#upload-%s opens it asking for that type', (bomType) => {
        const instance = dialog(`#upload-${bomType}`);
        expect(instance.uploadOpen).toBe(true);
        expect(instance.uploadRequest?.bomType).toBe(bomType);
    });

    test('#upload-artifact opens it on the default type', () => {
        const instance = dialog('#upload-artifact');
        expect(instance.uploadOpen).toBe(true);
        expect(instance.uploadRequest?.bomType).toBeNull();
    });

    test('a typed event opens it asking for that type', () => {
        const instance = dialog();
        instance.openFromEvent(openEvent({ bomType: 'vex' }));
        expect(instance.uploadOpen).toBe(true);
        expect(instance.uploadRequest?.bomType).toBe('vex');
    });

    test('a bare event opens it on the default type', () => {
        const instance = dialog();
        instance.openFromEvent(openEvent());
        expect(instance.uploadOpen).toBe(true);
        expect(instance.uploadRequest?.bomType).toBeNull();
    });

    test('every open is a new request, so a repeat while open still reaches the body', () => {
        const instance = dialog();
        instance.openFromEvent(openEvent({ bomType: 'vex' }));
        const first = instance.uploadRequest;
        instance.openFromEvent(openEvent({ bomType: 'vex' }));
        expect(instance.uploadRequest).not.toBe(first);
        expect(instance.uploadRequest!.seq).toBeGreaterThan(first!.seq);
    });

    test('a hash change opens it on the new type', () => {
        const instance = dialog();
        setHash('#upload-cbom');
        instance.openFromHash();
        expect(instance.uploadOpen).toBe(true);
        expect(instance.uploadRequest?.bomType).toBe('cbom');
    });
});

describe('the document uploader', () => {
    const documents = { bomTypes: false };

    test.each(['#upload-artifact', '#upload-sbom'])('%s still opens it', (hash) => {
        const instance = dialog(hash, documents);
        expect(instance.uploadOpen).toBe(true);
        expect(instance.uploadRequest?.bomType).toBeNull();
    });

    test.each(['#upload-cbom', '#upload-vex'])('%s leaves it closed', (hash) => {
        expect(dialog(hash, documents).uploadOpen).toBe(false);
    });

    test('a bare event opens it, a typed one does not', () => {
        const instance = dialog('', documents);
        instance.openFromEvent(openEvent({ bomType: 'vex' }));
        expect(instance.uploadOpen).toBe(false);
        instance.openFromEvent(openEvent());
        expect(instance.uploadOpen).toBe(true);
    });
});

describe('what the type select shows', () => {
    test('a typed request wins over the template default', () => {
        expect(resolveRequestedBomType(idle('sbom'), request('vex'), 'sbom')).toBe('vex');
        expect(resolveRequestedBomType(idle('sbom'), request('cbom'), 'sbom')).toBe('cbom');
    });

    test('a generic request returns to the default, so a typed open does not leak', () => {
        expect(resolveRequestedBomType(idle('vex'), request(null), 'sbom')).toBe('sbom');
        expect(resolveRequestedBomType(idle('vex'), request(null), 'cbom')).toBe('cbom');
    });

    test('no request leaves the select alone', () => {
        expect(resolveRequestedBomType(idle('cbom'), null, 'sbom')).toBe('cbom');
        expect(resolveRequestedBomType(idle('cbom'), undefined, 'sbom')).toBe('cbom');
    });

    test('an upload in progress keeps its type', () => {
        const state = { ...idle('cbom'), isUploading: true };
        expect(resolveRequestedBomType(state, request('vex'), 'sbom')).toBe('cbom');
        expect(resolveRequestedBomType(state, request(null), 'sbom')).toBe('cbom');
    });

    test('a VEX preview running or awaiting a decision keeps VEX', () => {
        const previewing = { ...idle('vex'), isPreviewing: true };
        const awaiting = { ...idle('vex'), preview: { would_suppress: 1 } };
        expect(resolveRequestedBomType(previewing, request('sbom'), 'sbom')).toBe('vex');
        expect(resolveRequestedBomType(awaiting, request('sbom'), 'sbom')).toBe('vex');
        expect(resolveRequestedBomType(awaiting, request(null), 'sbom')).toBe('vex');
    });
});
