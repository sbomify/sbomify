import Alpine from '../../core/js/alpine-init'
import { showSuccess, showError } from '../../core/js/alerts'
import { getCsrfToken } from '../../core/js/csrf'

const MAX_SBOM_SIZE = 10 * 1024 * 1024;
const ALLOWED_MIME_TYPES = ['application/json', 'text/plain'];
const ALLOWED_EXTENSIONS = ['.json', '.spdx', '.cdx'];

interface SbomUploadState {
    expanded: boolean
    isDragOver: boolean
    isUploading: boolean
    componentId: string
    abortController: AbortController | null
    handleDrop: (event: DragEvent) => void
    handleFileSelect: (event: Event) => void
    validateFile: (file: File) => string | null
    uploadFile: (file: File) => Promise<void>
    cleanup: () => void
}

export function registerSbomUpload(): void {
    Alpine.data('sbomUpload', (componentId: string): SbomUploadState => ({
        expanded: true,
        isDragOver: false,
        isUploading: false,
        componentId: componentId,
        abortController: null,

        validateFile(file: File): string | null {
            if (file.size > MAX_SBOM_SIZE) {
                return 'File size must be less than 10MB'
            }

            const fileExtension = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
            const hasValidType = ALLOWED_MIME_TYPES.includes(file.type);
            const hasValidExtension = ALLOWED_EXTENSIONS.includes(fileExtension);

            if (!hasValidType && !hasValidExtension) {
                return 'Please select a valid SBOM file (.json, .spdx, .cdx)'
            }

            return null
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

                const response = await fetch(`/api/v1/sboms/upload-file/${this.componentId}`, {
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
                    } catch (error) {
                        console.error('Failed to parse JSON response:', error);
                    }
                }

                if (response.ok) {
                    showSuccess('SBOM uploaded successfully! Reloading page...')
                    window.dispatchEvent(new CustomEvent('sbom-uploaded'))
                } else {
                    const errorMessage = (data.detail as string) || `Upload failed with status ${response.status}`
                    showError(errorMessage)
                    console.error('SBOM upload failed:', { status: response.status, data })
                }
            } catch (error) {
                if (error instanceof Error) {
                    if (error.name === 'AbortError') {
                        showError('Upload was cancelled.')
                    } else {
                        showError(`Network error: ${error.message}`)
                        console.error('SBOM upload error:', error)
                    }
                } else {
                    showError('An unexpected error occurred. Please try again.')
                    console.error('Unknown upload error:', error)
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
                this.uploadFile(files[0]);
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
                this.uploadFile(files[0]);
            }
            target.value = '';
        },

        cleanup(): void {
            if (this.abortController) {
                this.abortController.abort()
                this.abortController = null
            }
        }
    }))
}
