/**
 * Opens a component's uploader from the header menu, an empty state or a deep link.
 *
 * A BOM uploader can be asked for one artifact type: the window event
 * `open-upload` with `{ bomType: 'vex' }`, or the hashes `#upload-sbom`,
 * `#upload-cbom` and `#upload-vex`. `#upload-artifact` and a bare event open it
 * on the template's default type. Each open publishes a fresh `uploadRequest`,
 * so the dialog body can apply it even when the modal is already open;
 * `resolveRequestedBomType` decides what the type select then shows.
 *
 * A document uploader has no artifact types. It opens on the generic requests
 * and on the legacy `#upload-sbom` link, and ignores the typed ones, so a link
 * asking for a VEX never opens a document form.
 */
export const UPLOAD_BOM_TYPES = ['sbom', 'cbom', 'vex'] as const;
export type UploadBomType = (typeof UPLOAD_BOM_TYPES)[number];

export interface UploadRequest {
    /** null asks for the template default. */
    bomType: UploadBomType | null;
    seq: number;
}

export interface UploadDialogOptions {
    /** false for an uploader that takes no BOM types (documents). */
    bomTypes?: boolean;
}

export interface UploadTypeState {
    bomType: UploadBomType;
    isUploading: boolean;
    isPreviewing: boolean;
    preview: unknown;
}

const GENERIC_HASH = '#upload-artifact';
const LEGACY_HASH = '#upload-sbom';
const TYPED_HASH_PREFIX = '#upload-';

export function isUploadBomType(value: unknown): value is UploadBomType {
    return typeof value === 'string' && (UPLOAD_BOM_TYPES as readonly string[]).includes(value);
}

/** The type a hash asks for: undefined when it is not an upload link, null for the generic one. */
export function bomTypeFromHash(hash: string): UploadBomType | null | undefined {
    if (hash === GENERIC_HASH) return null;
    if (!hash.startsWith(TYPED_HASH_PREFIX)) return undefined;
    const bomType = hash.slice(TYPED_HASH_PREFIX.length);
    return isUploadBomType(bomType) ? bomType : undefined;
}

/** The type an `open-upload` event asks for; a missing or unknown type is a generic open. */
export function bomTypeFromDetail(detail: unknown): UploadBomType | null {
    const bomType = (detail as { bomType?: unknown } | null | undefined)?.bomType;
    return isUploadBomType(bomType) ? bomType : null;
}

/**
 * The type the select shows after a request. An upload or VEX preview in
 * progress keeps its type: the select is locked for it and switching would
 * change what the pending file is sent as. Otherwise the request wins over the
 * template default, and a generic request returns to that default, so a typed
 * open does not leak into the next ordinary one.
 */
export function resolveRequestedBomType(
    state: UploadTypeState,
    request: UploadRequest | null | undefined,
    initial: UploadBomType,
): UploadBomType {
    if (!request || state.isUploading || state.isPreviewing || state.preview) return state.bomType;
    return request.bomType ?? initial;
}

export function uploadDialog(options: UploadDialogOptions = {}) {
    const acceptsBomTypes = options.bomTypes !== false;
    return {
        uploadOpen: false,
        uploadRequest: null as UploadRequest | null,
        init() {
            this.openFromHash();
        },
        open(bomType: UploadBomType | null) {
            if (bomType && !acceptsBomTypes) return;
            this.uploadRequest = { bomType, seq: (this.uploadRequest?.seq ?? 0) + 1 };
            this.uploadOpen = true;
        },
        openFromEvent(event: Event) {
            this.open(bomTypeFromDetail((event as CustomEvent).detail));
        },
        openFromHash() {
            const hash = window.location.hash;
            if (!acceptsBomTypes && hash === LEGACY_HASH) {
                this.open(null);
                return;
            }
            const bomType = bomTypeFromHash(hash);
            if (bomType !== undefined) this.open(bomType);
        },
    };
}
