import Alpine from 'alpinejs';
import $axios, { confirmDelete } from '../utils';
import { showError, showSuccess } from '../alerts';

interface Identifier {
    id: string;
    type: string;
    value: string;
    created_at?: string;
}

interface IdentifierForm {
    id: string | null;
    type: string;
    value: string;
}

interface ProductIdentifiersParams {
    productId: string;
    initialIdentifiers?: Identifier[];
    canCreate?: boolean;
    canEdit?: boolean;
    canDelete?: boolean;
}

interface JsBarcodeLibrary {
    (selector: string | HTMLElement, value: string, options?: object): void;
}

declare global {
    interface Window {
        JsBarcode?: JsBarcodeLibrary;
    }
}

export function registerProductIdentifiers() {
    Alpine.data('productIdentifiers', ({
        productId,
        initialIdentifiers = [],
        canCreate = true,
        canEdit = true,
        canDelete = true
    }: ProductIdentifiersParams) => ({
        identifiers: initialIdentifiers as Identifier[],
        isLoading: false,
        showAddModal: false,
        showEditModal: false,
        form: {
            id: null,
            type: 'gtin',
            value: ''
        } as IdentifierForm,
        productId,
        canCreate,
        canEdit,
        canDelete,
        identifierTypes: [
            { value: 'gtin', label: 'GTIN (Global Trade Item Number)' },
            { value: 'sku', label: 'SKU (Stock Keeping Unit)' },
            { value: 'upc', label: 'UPC (Universal Product Code)' },
            { value: 'ean', label: 'EAN (European Article Number)' },
            { value: 'isbn', label: 'ISBN (International Standard Book Number)' },
            { value: 'asin', label: 'ASIN (Amazon Standard Identification Number)' },
            { value: 'mpn', label: 'MPN (Manufacturer Part Number)' },
            { value: 'custom', label: 'Custom' }
        ],

        init() {
            this.loadIdentifiers();
        },

        async loadIdentifiers() {
            this.isLoading = true;
            try {
                const response = await $axios.get(`/api/v1/products/${this.productId}/identifiers`);
                this.identifiers = response.data;
                this.$nextTick(() => this.renderBarcodes());
            } catch (error) {
                console.error('Failed to load identifiers:', error);
                showError('Failed to load identifiers');
            } finally {
                this.isLoading = false;
            }
        },

        openAddModal() {
            this.form = { id: null, type: 'gtin', value: '' };
            this.showAddModal = true;
        },

        openEditModal(identifier: Identifier) {
            this.form = { id: identifier.id, type: identifier.type, value: identifier.value };
            this.showEditModal = true;
        },

        closeModal() {
            this.showAddModal = false;
            this.showEditModal = false;
            this.form = { id: null, type: 'gtin', value: '' };
        },

        async submitForm() {
            try {
                if (this.form.id) {
                    await $axios.put(`/api/v1/products/${this.productId}/identifiers/${this.form.id}`, {
                        type: this.form.type,
                        value: this.form.value
                    });
                    showSuccess('Identifier updated successfully');
                } else {
                    await $axios.post(`/api/v1/products/${this.productId}/identifiers`, {
                        type: this.form.type,
                        value: this.form.value
                    });
                    showSuccess('Identifier added successfully');
                }
                this.closeModal();
                await this.loadIdentifiers();
            } catch (error) {
                console.error('Failed to save identifier:', error);
                showError('Failed to save identifier');
            }
        },

        async deleteIdentifier(identifier: Identifier) {
            const confirmed = await confirmDelete({
                itemName: `${identifier.type}: ${identifier.value}`,
                itemType: 'identifier'
            });

            if (!confirmed) return;

            try {
                await $axios.delete(`/api/v1/products/${this.productId}/identifiers/${identifier.id}`);
                showSuccess('Identifier deleted successfully');
                await this.loadIdentifiers();
            } catch (error) {
                console.error('Failed to delete identifier:', error);
                showError('Failed to delete identifier');
            }
        },

        renderBarcodes() {
            const JsBarcode = window.JsBarcode;
            if (!JsBarcode) return;

            this.identifiers.forEach((identifier: Identifier) => {
                const barcodeTypes = ['gtin', 'upc', 'ean', 'isbn'];
                if (!barcodeTypes.includes(identifier.type)) return;

                const barcodeElement = document.querySelector(`#barcode-${identifier.id}`);
                if (!barcodeElement) return;

                try {
                    let format = 'CODE128';
                    const valueLength = identifier.value.replace(/\D/g, '').length;

                    if (identifier.type === 'upc' && valueLength === 12) {
                        format = 'UPC';
                    } else if (identifier.type === 'ean') {
                        format = valueLength === 13 ? 'EAN13' : (valueLength === 8 ? 'EAN8' : 'CODE128');
                    } else if (identifier.type === 'isbn' && valueLength === 13) {
                        format = 'EAN13';
                    } else if (identifier.type === 'gtin') {
                        if (valueLength === 13) format = 'EAN13';
                        else if (valueLength === 12) format = 'UPC';
                        else if (valueLength === 8) format = 'EAN8';
                    }

                    JsBarcode(barcodeElement, identifier.value, {
                        format,
                        width: 1.5,
                        height: 50,
                        displayValue: true,
                        fontSize: 12,
                        margin: 5
                    });
                } catch (error) {
                    console.warn(`Failed to render barcode for ${identifier.id}:`, error);
                }
            });
        },

        getTypeLabel(type: string): string {
            const found = this.identifierTypes.find((t: { value: string; label: string }) => t.value === type);
            return found ? found.label : type;
        },

        canShowBarcode(type: string): boolean {
            return ['gtin', 'upc', 'ean', 'isbn'].includes(type);
        }
    }));
}
