import Alpine from '../../core/js/alpine-init';
import type { SupplierInfo } from '../../core/js/types';

interface SupplierEditorProps {
    supplier: SupplierInfo;
}

export function registerSupplierEditor() {
    Alpine.data('supplierEditor', (props: SupplierEditorProps) => ({
        supplier: {
            name: props.supplier?.name || null,
            url: Array.isArray(props.supplier?.url) ? props.supplier.url :
                (props.supplier?.url ? [props.supplier.url] : []),
            address: props.supplier?.address || null,
            contacts: props.supplier?.contacts || []
        } as SupplierInfo,
        newUrlInput: '',
        boundMetadataLoadedHandler: null as ((e: Event) => void) | null,

        init() {
            let previousSupplier = JSON.stringify(this.supplier);
            this.$watch('supplier', () => {
                const current = JSON.stringify(this.supplier);
                if (current !== previousSupplier) {
                    previousSupplier = current;
                    this.dispatchUpdate();
                }
            });

            this.boundMetadataLoadedHandler = (e: Event) => {
                const detail = (e as CustomEvent).detail;
                if (detail && detail.supplier) {
                    const newSupplier = detail.supplier;
                    this.supplier = {
                        name: newSupplier.name || null,
                        url: Array.isArray(newSupplier.url) ? newSupplier.url :
                            (newSupplier.url ? [newSupplier.url] : []),
                        address: newSupplier.address || null,
                        contacts: newSupplier.contacts || []
                    };
                }
            };
            window.addEventListener('component-metadata-loaded', this.boundMetadataLoadedHandler);
        },

        destroy() {
            if (this.boundMetadataLoadedHandler) {
                window.removeEventListener('component-metadata-loaded', this.boundMetadataLoadedHandler);
                this.boundMetadataLoadedHandler = null;
            }
        },

        addUrl() {
            if (!this.supplier.url) {
                this.supplier.url = [];
            }
            this.supplier.url.push('');
            this.dispatchUpdate();
        },

        addUrlFromInput() {
            if (this.newUrlInput.trim()) {
                if (!this.supplier.url) {
                    this.supplier.url = [];
                }
                this.supplier.url.push(this.newUrlInput.trim());
                this.newUrlInput = '';
                this.dispatchUpdate();
            }
        },

        updateUrl(index: number, value: string) {
            if (this.supplier.url) {
                this.supplier.url[index] = value;
                this.dispatchUpdate();
            }
        },

        removeUrl(index: number) {
            if (this.supplier.url && this.supplier.url.length > 1) {
                this.supplier.url.splice(index, 1);
                this.dispatchUpdate();
            }
        },

        dispatchUpdate() {
            this.$dispatch('supplier-updated', { supplier: this.supplier });
        }
    }));
}
