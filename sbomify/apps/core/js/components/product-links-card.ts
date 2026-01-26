import Alpine from 'alpinejs';

interface ProductLinksCardData {
    showAddModal: boolean;
    showEditModal: boolean;
    showDeleteModal: boolean;
    editId: string;
    editType: string;
    editTitle: string;
    editUrl: string;
    editDescription: string;
    deleteId: string;
    deleteName: string;
    productId: number;
    cardElementId: string;
    updateUrl: string;
    $el: HTMLElement;
    handleAddSubmit: (event: Event) => Promise<void>;
    handleEditSubmit: (event: Event) => Promise<void>;
    handleDelete: () => Promise<void>;
    openEditModal: (id: string, type: string, title: string, url: string, description: string) => void;
    openDeleteModal: (id: string, name: string) => void;
    getCsrfToken: () => string;
}

/**
 * Product Links Card Component
 * Handles CRUD operations for product links
 */
export function registerProductLinksCard(): void {
    Alpine.data('productLinksCard', ({
        productId,
        cardElementId,
        updateUrl
    }: { productId: number; cardElementId: string; updateUrl: string }): ProductLinksCardData => {
        return {
            showAddModal: false,
            showEditModal: false,
            showDeleteModal: false,
            editId: '',
            editType: '',
            editTitle: '',
            editUrl: '',
            editDescription: '',
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
                    console.error('Error adding link:', error);
                }
            },
            
            async handleEditSubmit(event: Event) {
                event.preventDefault();
                const form = event.target as HTMLFormElement;
                const formData = new FormData(form);
                formData.set('link_id', this.editId);
                
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
                    console.error('Error updating link:', error);
                }
            },
            
            async handleDelete() {
                const formData = new FormData();
                formData.append('csrfmiddlewaretoken', this.getCsrfToken());
                formData.append('action', 'delete');
                formData.append('link_id', this.deleteId);
                
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
                    console.error('Error deleting link:', error);
                }
            },
            
            getCsrfToken(): string {
                const cookieValue = document.cookie
                    .split('; ')
                    .find(row => row.startsWith('csrftoken='))
                    ?.split('=')[1] || '';
                return cookieValue;
            },
            
            openEditModal(id: string, type: string, title: string, url: string, description: string) {
                this.editId = id;
                this.editType = type;
                this.editTitle = title;
                this.editUrl = url;
                this.editDescription = description;
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
