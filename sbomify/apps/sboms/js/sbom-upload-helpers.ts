export const MAX_UPLOAD_SIZE = 100 * 1024 * 1024;
export const ALLOWED_MIME_TYPES = ['application/json', 'text/xml', 'application/xml'];
export const ALLOWED_EXTENSIONS = ['.json', '.spdx', '.cdx', '.xml'];

export type UploadBomType = 'sbom' | 'vex'

export function bomTypeLabel(bomType: UploadBomType): string {
    return bomType === 'vex' ? 'VEX' : 'SBOM'
}

export function buildUploadEndpoint(componentId: string, bomType: UploadBomType): string {
    // The default SBOM case must omit bom_type: the server's CBOM
    // auto-detection only runs when the caller leaves it unset.
    const base = `/api/v1/sboms/upload-file/${componentId}`
    return bomType === 'sbom' ? base : `${base}?bom_type=${encodeURIComponent(bomType)}`
}

export function validateUploadFile(file: File, bomType: UploadBomType): string | null {
    if (file.size > MAX_UPLOAD_SIZE) {
        return 'File size must be 100MB or smaller'
    }

    const dotIndex = file.name.lastIndexOf('.')
    const fileExtension = dotIndex >= 0 ? file.name.toLowerCase().slice(dotIndex) : '';
    const hasValidType = ALLOWED_MIME_TYPES.includes(file.type);
    const hasValidExtension = ALLOWED_EXTENSIONS.includes(fileExtension);

    if (!hasValidType && !hasValidExtension) {
        const allowed = bomType === 'vex' ? '.json, .cdx, .xml' : '.json, .spdx, .cdx'
        return `Please select a valid ${bomTypeLabel(bomType)} file (${allowed})`
    }

    // XML is only meaningful for CycloneDX VEX; SBOM uploads are JSON formats.
    // Catch by extension AND by MIME (a .cdx file the browser tags as XML).
    const isXml = fileExtension === '.xml' || file.type === 'application/xml' || file.type === 'text/xml'
    if (bomType === 'sbom' && isXml) {
        return 'XML uploads are supported for VEX only; SBOMs must be CycloneDX or SPDX JSON'
    }

    // Catch both bare ".spdx" and the common ".spdx.json" naming. The server
    // inspects the content either way; this just fails obvious cases early.
    if (bomType === 'vex' && /\.spdx(\.|$)/.test(file.name.toLowerCase())) {
        return 'SPDX files are SBOM-only; a VEX must be CycloneDX, OpenVEX, or CSAF (.json, .cdx, .xml)'
    }

    return null
}

export function buildPreviewEndpoint(componentId: string): string {
    return `/api/v1/vulnerability-scanning/components/${componentId}/vex-preview`
}
