import Alpine from 'alpinejs';

interface ProductIdentifiersCardData {
    showAddModal: boolean;
    showEditModal: boolean;
    showDeleteModal: boolean;
    editId: string;
    editType: string;
    editValue: string;
    deleteId: string;
    deleteName: string;
    productId: number;
    cardElementId: string;
    updateUrl: string;
    $el: HTMLElement;
    handleAddSubmit: (event: Event) => Promise<void>;
    handleEditSubmit: (event: Event) => Promise<void>;
    handleDelete: () => Promise<void>;
    openEditModal: (id: string, type: string, value: string) => void;
    openDeleteModal: (id: string, name: string) => void;
    getCsrfToken: () => string;
}

/**
 * Product Identifiers Card Component
 * Handles CRUD operations for product identifiers
 */
export function registerProductIdentifiersCard(): void {
    Alpine.data('productIdentifiersCard', ({
        productId,
        cardElementId,
        updateUrl
    }: { productId: number; cardElementId: string; updateUrl: string }): ProductIdentifiersCardData => {
        return {
            showAddModal: false,
            showEditModal: false,
            showDeleteModal: false,
            editId: '',
            editType: '',
            editValue: '',
            deleteId: '',
            deleteName: '',
            productId,
            cardElementId,
            updateUrl,
            $el: {} as HTMLElement, // Will be set by Alpine
            
            async handleAddSubmit(event: Event) {
                event.preventDefault();
                const form = event.target as HTMLFormElement;
                const formData = new FormData(form);
                
                try {
                    const response = await fetch(this.updateUrl, {
                        method: 'POST',
                        body: formData
                    });
                    
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    
                    const html = await response.text();
                    const cardElement = document.getElementById(this.cardElementId);
                    if (cardElement) {
                        cardElement.outerHTML = html;
                        // Re-initialize Alpine on the new content
                        if (window.Alpine) {
                            window.Alpine.initTree(cardElement.parentElement || document.body);
                        }
                    }
                    this.showAddModal = false;
                } catch (error) {
                    console.error('Error adding identifier:', error);
                }
            },
            
            async handleEditSubmit(event: Event) {
                event.preventDefault();
                const form = event.target as HTMLFormElement;
                const formData = new FormData(form);
                formData.set('identifier_id', this.editId);
                
                try {
                    const response = await fetch(this.updateUrl, {
                        method: 'POST',
                        body: formData
                    });
                    
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    
                    const html = await response.text();
                    const cardElement = document.getElementById(this.cardElementId);
                    if (cardElement) {
                        cardElement.outerHTML = html;
                        // Re-initialize Alpine on the new content
                        if (window.Alpine) {
                            window.Alpine.initTree(cardElement.parentElement || document.body);
                        }
                    }
                    this.showEditModal = false;
                } catch (error) {
                    console.error('Error updating identifier:', error);
                }
            },
            
            async handleDelete() {
                const formData = new FormData();
                formData.append('csrfmiddlewaretoken', this.getCsrfToken());
                formData.append('action', 'delete');
                formData.append('identifier_id', this.deleteId);
                
                try {
                    const response = await fetch(this.updateUrl, {
                        method: 'POST',
                        body: formData
                    });
                    
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    
                    const html = await response.text();
                    const cardElement = document.getElementById(this.cardElementId);
                    if (cardElement) {
                        cardElement.outerHTML = html;
                        // Re-initialize Alpine on the new content
                        if (window.Alpine) {
                            window.Alpine.initTree(cardElement.parentElement || document.body);
                        }
                    }
                    this.showDeleteModal = false;
                } catch (error) {
                    console.error('Error deleting identifier:', error);
                }
            },
            
            getCsrfToken(): string {
                const cookieValue = document.cookie
                    .split('; ')
                    .find(row => row.startsWith('csrftoken='))
                    ?.split('=')[1] || '';
                return cookieValue;
            },
            
            openEditModal(id: string, type: string, value: string) {
                this.editId = id;
                this.editType = type;
                this.editValue = value;
                this.showEditModal = true;
            },
            
            openDeleteModal(id: string, name: string) {
                this.deleteId = id;
                this.deleteName = name;
                this.showDeleteModal = true;
            }
        };
    });
}
