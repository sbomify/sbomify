import Alpine from 'alpinejs';
import $axios from '../utils';

interface EditableSingleFieldParams {
    itemType: string;
    itemId: string;
    itemValue: string;
    fieldName?: string;
    fieldType?: string;
    displayValue?: string;
    placeholder?: string;
}

export function registerEditableSingleField() {
    Alpine.data('editableSingleField', ({
        itemType,
        itemId,
        itemValue,
        fieldName = 'name',
        fieldType = 'text',
        displayValue = '',
        placeholder = ''
    }: EditableSingleFieldParams) => ({
        isEditing: false,
        fieldValue: itemValue,
        originalValue: itemValue,
        errorMessage: '',
        itemType,
        itemId,
        fieldName,
        fieldType,
        displayValue: displayValue || itemValue,
        placeholder,

        get isTextarea(): boolean {
            return this.fieldType === 'textarea';
        },

        get inputType(): string {
            switch (this.fieldType) {
                case 'datetime':
                case 'datetime-local':
                    return 'datetime-local';
                case 'date':
                    return 'date';
                case 'email':
                    return 'email';
                case 'url':
                    return 'url';
                case 'number':
                    return 'number';
                default:
                    return 'text';
            }
        },

        get displayText(): string {
            return this.displayValue || this.fieldValue;
        },

        startEdit() {
            this.isEditing = true;
            this.fieldValue = this.originalValue;
        },

        cancelEdit() {
            this.isEditing = false;
            this.fieldValue = this.originalValue;
        },

        normalizeValueForApi(): string | number | boolean | null {
            if (typeof this.fieldValue === 'string') {
                const trimmedValue = this.fieldValue.trim();
                if (!trimmedValue) return null;

                if (['date', 'datetime', 'datetime-local'].includes(this.fieldType)) {
                    const parsedDate = new Date(trimmedValue);
                    if (Number.isNaN(parsedDate.getTime())) {
                        throw new Error('Please enter a valid date/time value.');
                    }
                    return parsedDate.toISOString();
                }
                return trimmedValue;
            }
            return this.fieldValue;
        },

        async updateField() {
            this.errorMessage = '';
            const data: Record<string, string | number | boolean | null> = {};

            try {
                data[this.fieldName] = this.normalizeValueForApi();
            } catch (error) {
                this.errorMessage = (error as Error).message;
                this.fieldValue = this.originalValue;
                return;
            }

            let apiUrl: string;
            switch (this.itemType) {
                case 'workspace':
                    apiUrl = `/api/v1/workspaces/${this.itemId}`;
                    break;
                case 'component':
                    apiUrl = `/api/v1/components/${this.itemId}`;
                    break;
                case 'project':
                    apiUrl = `/api/v1/projects/${this.itemId}`;
                    break;
                case 'product':
                    apiUrl = `/api/v1/products/${this.itemId}`;
                    break;
                case 'release':
                    apiUrl = `/api/v1/releases/${this.itemId}`;
                    break;
                default:
                    this.errorMessage = 'Unknown item type';
                    return;
            }

            try {
                const response = await $axios.patch(apiUrl, data);
                if (response.status < 200 || response.status >= 300) {
                    throw new Error('Network response was not ok. ' + response.statusText);
                }
                this.isEditing = false;
                window.location.reload();
            } catch (error) {
                this.fieldValue = this.originalValue;
                this.errorMessage = 'Error updating field. ' + (error as Error).message;
            }
        },

        handleKeyup(event: KeyboardEvent) {
            if (event.key === 'Escape') {
                this.cancelEdit();
            } else if (event.key === 'Enter' && !this.isTextarea) {
                this.updateField();
            }
        }
    }));
}
