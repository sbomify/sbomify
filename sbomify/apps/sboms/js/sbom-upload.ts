import Alpine from 'alpinejs'
import { showSuccess, showError } from '../../core/js/alerts'

interface SbomUploadState {
    isDragOver: boolean
    isUploading: boolean
    componentId: string
    handleDrop: (event: DragEvent) => void
    handleFileSelect: (event: Event) => void
    validateFile: (file: File) => string | null
    uploadFile: (file: File) => Promise<void>
    getCsrfToken: () => string
}

export function registerSbomUpload(): void {
    Alpine.data('sbomUpload', (componentId: string): SbomUploadState => ({
        isDragOver: false,
        isUploading: false,
        componentId: componentId,

        validateFile(file: File): string | null {
            // Check file size (max 10MB)
            const maxSize = 10 * 1024 * 1024
            if (file.size > maxSize) {
                return 'File size must be less than 10MB'
            }

            // Check file type
            const allowedTypes = ['application/json', 'text/plain']
            const allowedExtensions = ['.json', '.spdx', '.cdx']
            const fileExtension = file.name.toLowerCase().slice(file.name.lastIndexOf('.'))

            if (!allowedTypes.includes(file.type) && !allowedExtensions.includes(fileExtension)) {
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

            this.isUploading = true

            try {
                const formData = new FormData()
                formData.append('sbom_file', file)
                formData.append('component_id', this.componentId)

                const response = await fetch(`/api/v1/sboms/upload-file/${this.componentId}`, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-CSRFToken': this.getCsrfToken()
                    }
                })

                const data = await response.json()

                if (response.ok) {
                    showSuccess('SBOM uploaded successfully!')
                    // Refresh the page after 2 seconds to show the new SBOM
                    setTimeout(() => {
                        window.location.reload()
                    }, 2000)
                } else {
                    showError(data.detail || 'Upload failed')
                }
            } catch {
                showError('Network error occurred. Please try again.')
            } finally {
                this.isUploading = false
            }
        },

        handleDrop(event: DragEvent): void {
            event.preventDefault()
            this.isDragOver = false

            const files = event.dataTransfer?.files
            if (files && files.length > 0) {
                this.uploadFile(files[0])
            }
        },

        handleFileSelect(event: Event): void {
            const target = event.target as HTMLInputElement
            const files = target.files
            if (files && files.length > 0) {
                this.uploadFile(files[0])
            }
        },

        getCsrfToken(): string {
            const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
            if (!token) {
                // Fallback to cookie method
                const cookieValue = document.cookie
                    .split('; ')
                    .find(row => row.startsWith('csrftoken='))
                    ?.split('=')[1]
                return cookieValue || ''
            }
            return token
        }
    }))
}
