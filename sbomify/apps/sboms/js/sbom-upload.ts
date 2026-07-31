import Alpine from '../../core/js/alpine-init'
import { showSuccess, showError } from '../../core/js/alerts'
import { getCsrfToken } from '../../core/js/csrf'
import { bomTypeLabel, buildPreviewEndpoint, buildUploadEndpoint, validateUploadFile, type UploadBomType } from './sbom-upload-helpers'

interface VexPreview {
    format: string
    suppressing_statements: number
    findings_checked: number
    would_suppress: number
    already_suppressed: number
    unmatched_statements: number
    matched: Array<{ id: string; package: string | null; version: string | null; state: string }>
}

interface SbomUploadState {
    expanded: boolean
    isDragOver: boolean
    isUploading: boolean
    isPreviewing: boolean
    componentId: string
    bomType: UploadBomType
    preview: VexPreview | null
    pendingFile: File | null
    abortController: AbortController | null
    readonly bomTypeLabel: string
    handleDrop: (event: DragEvent) => void
    handleFileSelect: (event: Event) => void
    handleFile: (file: File) => void
    runPreview: (file: File) => Promise<void>
    applyPreview: () => Promise<void>
    cancelPreview: () => void
    validateFile: (file: File) => string | null
    uploadFile: (file: File) => Promise<void>
    cleanup: () => void
}

export function registerSbomUpload(): void {
    Alpine.data('sbomUpload', (componentId: string, hasSboms: boolean = false): SbomUploadState => ({
        expanded: !hasSboms,
        isDragOver: false,
        isUploading: false,
        isPreviewing: false,
        componentId: componentId,
        bomType: 'sbom' as UploadBomType,
        preview: null,
        pendingFile: null,
        abortController: null,

        get bomTypeLabel(): string {
            return bomTypeLabel(this.bomType)
        },

        validateFile(file: File): string | null {
            return validateUploadFile(file, this.bomType)
        },

        async uploadFile(file: File): Promise<void> {
            const validationError = this.validateFile(file)
            if (validationError) {
                showError(validationError)
                return
            }

            if (this.isUploading) {
                showError('An upload is already in progress. Please wait.')
                return
            }

            this.isUploading = true
            this.abortController = new AbortController()

            try {
                const formData = new FormData()
                formData.append('sbom_file', file)
                formData.append('component_id', this.componentId)

                const csrfToken = getCsrfToken()

                const response = await fetch(buildUploadEndpoint(this.componentId, this.bomType), {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-CSRFToken': csrfToken
                    },
                    signal: this.abortController.signal
                })

                let data: Record<string, unknown> = {};
                const contentType = response.headers.get('content-type');

                if (contentType?.includes('application/json')) {
                    try {
                        data = await response.json();
                    } catch {
                        // JSON parse failed, continue with empty data
                    }
                }

                if (response.ok) {
                    showSuccess(`${this.bomTypeLabel} uploaded successfully! Reloading page...`)
                    window.dispatchEvent(new CustomEvent('sbom-uploaded'))
                } else {
                    const errorMessage = (data.detail as string) || `Upload failed with status ${response.status}`
                    showError(errorMessage)
                }
            } catch (error) {
                if (error instanceof Error) {
                    if (error.name === 'AbortError') {
                        showError('Upload was cancelled.')
                    } else {
                        showError(`Network error: ${error.message}`)
                    }
                } else {
                    showError('An unexpected error occurred. Please try again.')
                }
            } finally {
                this.isUploading = false
                this.abortController = null
            }
        },

        handleDrop(event: DragEvent): void {
            event.preventDefault();
            this.isDragOver = false;

            if (this.isUploading) {
                return;
            }

            const files = event.dataTransfer?.files;
            if (files?.[0]) {
                this.handleFile(files[0]);
            }
        },

        handleFileSelect(event: Event): void {
            const target = event.target as HTMLInputElement;

            if (this.isUploading) {
                showError('An upload is already in progress. Please wait.')
                target.value = '';
                return;
            }

            const files = target.files;
            if (files?.[0]) {
                this.handleFile(files[0]);
            }
            target.value = '';
        },

        handleFile(file: File): void {
            // A VEX changes which findings the whole workspace sees as open, so
            // it gets a dry-run preview before anything is stored. SBOMs upload
            // directly as before.
            if (this.bomType === 'vex') {
                this.runPreview(file);
            } else {
                this.uploadFile(file);
            }
        },

        async runPreview(file: File): Promise<void> {
            if (this.isPreviewing) {
                showError('A preview is already running. Please wait.')
                return
            }
            const validationError = this.validateFile(file)
            if (validationError) {
                showError(validationError)
                return
            }
            this.isPreviewing = true
            try {
                // Raw bytes, not file.text(): the server sniffs JSON vs XML
                // itself, and a decode/re-encode round-trip would corrupt
                // non-UTF-8 XML and double the memory for large files.
                const response = await fetch(buildPreviewEndpoint(this.componentId), {
                    method: 'POST',
                    body: file,
                    headers: {
                        'Content-Type': file.type || 'application/octet-stream',
                        'X-CSRFToken': getCsrfToken()
                    }
                })
                const data = await response.json().catch(() => ({}))
                if (!response.ok) {
                    showError((data.detail as string) || `Preview failed with status ${response.status}`)
                    return
                }
                this.preview = data as VexPreview
                this.pendingFile = file
            } catch (error) {
                showError(error instanceof Error ? `Preview failed: ${error.message}` : 'Preview failed')
            } finally {
                this.isPreviewing = false
            }
        },

        async applyPreview(): Promise<void> {
            const file = this.pendingFile
            this.preview = null
            this.pendingFile = null
            if (file) {
                await this.uploadFile(file)
            }
        },

        cancelPreview(): void {
            this.preview = null
            this.pendingFile = null
        },

        cleanup(): void {
            if (this.abortController) {
                this.abortController.abort()
                this.abortController = null
            }
        }
    }))
}
