import Alpine from 'alpinejs';

interface FileDragAndDropParams {
    accept: string;
    existingUrl: string;
    fieldName: string;
}

export function registerFileDragAndDrop() {
    Alpine.data('fileDragAndDrop', ({ accept, existingUrl, fieldName }: FileDragAndDropParams) => {
        return {
            file: null as File | null,
            previewUrl: null as string | null,
            existingUrl,
            accept,
            fieldName,
            dragover: false,

            get isEmpty() {
                return !this.file && !this.existingUrl;
            },

            get hasFile() {
                return !!this.file || !!this.existingUrl;
            },

            get showExisting() {
                return !!this.existingUrl && !this.file;
            },

            get isImagePreview() {
                return !!this.file && this.isImage(this.file);
            },

            get acceptHint() {
                if (!this.accept) return '';
                return `Accepted: ${this.accept}`;
            },

            isImage(file: File | null) {
                if (!file) return false;
                if (!file.type) return false;
                return file.type.startsWith('image/');
            },

            cleanupPreview() {
                if (!this.previewUrl) return;
                URL.revokeObjectURL(this.previewUrl);
                this.previewUrl = null;
            },

            emitSelected(file: File) {
                if (!file) return;

                this.$dispatch('file-selected', {
                    field: this.fieldName,
                    file,
                });
            },

            handleFileSelect(e: Event) {
                const target = e.target as HTMLInputElement;
                if (!target?.files?.length) return;
                this.setFile(target.files[0]);
            },

            handleDrop(e: DragEvent) {
                this.dragover = false;

                if (!e?.dataTransfer?.files?.length) return;
                this.setFile(e.dataTransfer.files[0]);
            },

            setFile(file: File) {
                if (!file) return;

                this.cleanupPreview();
                this.file = file;

                if (!this.isImage(file)) {
                    this.emitSelected(file);
                    return;
                }

                this.previewUrl = URL.createObjectURL(file);
                this.emitSelected(file);
            },

            removeFile() {
                if (!this.file) return;

                this.cleanupPreview();
                this.file = null;

                const fileInput = (this as any).$refs?.fileInput as HTMLInputElement;
                if (fileInput) {
                    fileInput.value = '';
                }

                this.$dispatch('file-removed', {
                    field: this.fieldName
                });
            },

            removeExistingFile() {
                if (!this.existingUrl) return;

                this.existingUrl = '';

                this.$dispatch('existing-file-removed', {
                    field: this.fieldName
                });
            }
        };
    });
}
