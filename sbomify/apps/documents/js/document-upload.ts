import Alpine from '../../core/js/alpine-init';
import { showSuccess, showError } from '../../core/js/alerts';
import { getCsrfToken } from '../../core/js/csrf';

const MAX_FILE_SIZE = 50 * 1024 * 1024;

export function registerDocumentUpload(): void {
    Alpine.data('documentUpload', (componentId: string) => ({
        componentId,
        isExpanded: (() => {
            const stored = localStorage.getItem('card-collapse-document-upload');
            if (stored !== null) return stored === 'true';
            return false;
        })(),
        isDragOver: false,
        isUploading: false,
        selectedFile: null as File | null,
        documentVersion: '1.0',
        documentType: '',
        documentDescription: '',

        init() {
            this.$watch('isExpanded', (val: boolean) => {
                localStorage.setItem('card-collapse-document-upload', val.toString());
            });
        },

        toggleExpanded() {
            this.isExpanded = !this.isExpanded;
        },

        get isFormValid(): boolean {
            return this.selectedFile !== null && this.documentVersion.trim().length > 0;
        },

        formatFileSize(bytes: number): string {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        },

        validateFile(file: File): string | null {
            if (file.size > MAX_FILE_SIZE) {
                return 'File size must be less than 50MB';
            }
            return null;
        },

        clearSelectedFile(): void {
            this.selectedFile = null;
            const fileInput = this.$el.querySelector('input[type="file"]') as HTMLInputElement;
            if (fileInput) {
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

            this.isUploading = true;

            try {
                const formData = new FormData();
                formData.append('document_file', this.selectedFile);
                formData.append('component_id', this.componentId);
                formData.append('version', this.documentVersion.trim());
                if (this.documentType) {
                    formData.append('document_type', this.documentType);
                }
                if (this.documentDescription.trim()) {
                    formData.append('description', this.documentDescription.trim());
                }

                const response = await fetch('/api/v1/documents/', {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-CSRFToken': getCsrfToken()
                    }
                });

                let data: Record<string, unknown>;
                try {
                    data = await response.json();
                } catch {
                    data = {};
                }

                if (response.ok) {
                    showSuccess('Document uploaded successfully!');
                    this.documentVersion = '1.0';
                    this.documentType = '';
                    this.documentDescription = '';
                    this.clearSelectedFile();
                    window.dispatchEvent(new CustomEvent('document-uploaded'));
                } else {
                    showError((data.detail as string) || 'Upload failed');
                }
            } catch {
                showError('Network error occurred. Please try again.');
            } finally {
                this.isUploading = false;
            }
        },

        handleDrop(event: DragEvent): void {
            event.preventDefault();
            this.isDragOver = false;

            if (this.isUploading) {
                return;
            }

            const files = event.dataTransfer?.files;
            if (files && files.length > 0) {
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
            if (files && files.length > 0) {
                const file = files[0];
                const validationError = this.validateFile(file);
                if (validationError) {
                    showError(validationError);
                    target.value = '';
                    return;
                }
                this.selectedFile = file;
            }
        }
    }));
}
