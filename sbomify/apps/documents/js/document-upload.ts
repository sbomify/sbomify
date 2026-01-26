import Alpine from '../../core/js/alpine-init';
import { showSuccess, showError } from '../../core/js/alerts';
import { getCsrfToken } from '../../core/js/csrf';

const MAX_FILE_SIZE = 50 * 1024 * 1024;
const FILE_SIZE_UNITS = ['Bytes', 'KB', 'MB', 'GB'] as const;

export function registerDocumentUpload(): void {
    Alpine.data('documentUpload', (componentId: string) => ({
        componentId,
        // Use $persist for expanded state - auto-syncs with localStorage
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        expanded: (Alpine as any).$persist(true).as('document-upload-expanded'),
        isDragOver: false,
        isUploading: false,
        selectedFile: null as File | null,
        documentVersion: '1.0',
        documentType: '',
        documentTypeSubcategories: {} as Record<string, { field_name: string; choices: [string, string][]; label: string }>,
        documentSubcategory: '',
        documentDescription: '',
        abortController: null as AbortController | null,

        init() {
            // Parse document type subcategories from JSON script tag
            const subcategoriesElement = document.getElementById(`document-type-subcategories-${this.componentId}`);
            if (subcategoriesElement) {
                try {
                    this.documentTypeSubcategories = JSON.parse(subcategoriesElement.textContent || '{}');
                } catch (error) {
                    console.error('Error parsing document type subcategories:', error);
                    this.documentTypeSubcategories = {};
                }
            }
        },

        get currentSubcategoryInfo() {
            if (!this.documentType || !this.documentTypeSubcategories[this.documentType]) {
                return null;
            }
            return this.documentTypeSubcategories[this.documentType];
        },

        get isFormValid(): boolean {
            return this.selectedFile !== null && this.documentVersion.trim().length > 0;
        },

        formatFileSize(bytes: number): string {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + FILE_SIZE_UNITS[i];
        },

        validateFile(file: File): string | null {
            if (file.size > MAX_FILE_SIZE) {
                return 'File size must be less than 50MB';
            }
            return null;
        },

        clearSelectedFile(): void {
            this.selectedFile = null;
            const fileInput = this.$el.querySelector('input[type="file"]');
            if (fileInput instanceof HTMLInputElement) {
                fileInput.value = '';
            }
        },

        async saveDocument(): Promise<void> {
            if (!this.selectedFile) {
                showError('Please select a file to upload');
                return;
            }

            const validationError = this.validateFile(this.selectedFile);
            if (validationError) {
                showError(validationError);
                return;
            }

            if (!this.documentVersion.trim()) {
                showError('Please specify a document version');
                return;
            }

            if (this.isUploading) {
                showError('An upload is already in progress. Please wait.');
                return;
            }

            this.isUploading = true;
            this.abortController = new AbortController();

            try {
                const formData = new FormData();
                formData.append('document_file', this.selectedFile);
                formData.append('component_id', this.componentId);
                formData.append('version', this.documentVersion.trim());
                if (this.documentType) {
                    formData.append('document_type', this.documentType);
                }
                // Add subcategory if document type has subcategories and one is selected
                if (this.currentSubcategoryInfo && this.documentSubcategory) {
                    formData.append(this.currentSubcategoryInfo.field_name, this.documentSubcategory);
                }
                if (this.documentDescription.trim()) {
                    formData.append('description', this.documentDescription.trim());
                }

                const csrfToken = getCsrfToken();

                const response = await fetch('/api/v1/documents/', {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-CSRFToken': csrfToken
                    },
                    signal: this.abortController.signal
                });

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
                    showSuccess('Document uploaded successfully!');
                    this.documentVersion = '1.0';
                    this.documentType = '';
                    this.documentSubcategory = '';
                    this.documentDescription = '';
                    this.clearSelectedFile();
                    window.dispatchEvent(new CustomEvent('document-uploaded'));
                } else {
                    const errorMessage = (data.detail as string) || `Upload failed with status ${response.status}`;
                    showError(errorMessage);
                    console.error('Document upload failed:', { status: response.status, data });
                }
            } catch (error) {
                if (error instanceof Error) {
                    if (error.name === 'AbortError') {
                        showError('Upload was cancelled.');
                    } else {
                        showError(`Network error: ${error.message}`);
                        console.error('Document upload error:', error);
                    }
                } else {
                    showError('An unexpected error occurred. Please try again.');
                    console.error('Unknown upload error:', error);
                }
            } finally {
                this.isUploading = false;
                this.abortController = null;
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
                const file = files[0];
                const validationError = this.validateFile(file);
                if (validationError) {
                    showError(validationError);
                    return;
                }
                this.selectedFile = file;
            }
        },

        handleFileSelect(event: Event): void {
            const target = event.target as HTMLInputElement;

            if (this.isUploading) {
                target.value = '';
                return;
            }

            const files = target.files;
            if (files?.[0]) {
                const file = files[0];
                const validationError = this.validateFile(file);
                if (validationError) {
                    showError(validationError);
                    target.value = '';
                    return;
                }
                this.selectedFile = file;
            }
        },

        cleanup(): void {
            if (this.abortController) {
                this.abortController.abort();
                this.abortController = null;
            }
        }
    }));
}
