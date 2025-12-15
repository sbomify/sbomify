import Alpine from 'alpinejs';
import { Modal } from 'bootstrap';

const VALID_WORKSPACE_KEY_PATTERN = /^[a-zA-Z0-9_-]+$/;
const SEARCH_DEBOUNCE_MS = 150;
const MODAL_TRANSITION_DELAY_MS = 250;

interface WorkspaceSwitcherData {
    open: boolean;
    search: string;
    selected: string;
    currentWorkspace: string;
    currentView: string;
    switchUrl: string;
    teamsDashboardUrl: string;
    isSwitching: boolean;
    searchTimeout: ReturnType<typeof setTimeout> | null;
    filteredWorkspaces: Array<{ key: string; name: string }>;
    $el: HTMLElement;
    $watch?: (property: string, callback: (value: unknown) => void) => void;
    $nextTick?: (callback: () => void) => void;
    init: () => void;
    isVisible: (name: string) => boolean;
    toggleModal: () => void;
    closeModal: () => void;
    updateBodyClass: (openState?: boolean) => void;
    switchWorkspace: () => void;
    openNewWorkspaceModal: () => void;
    handleKeydown: (event: KeyboardEvent) => void;
    updateFilteredWorkspaces: () => void;
    debouncedSearch: () => void;
    destroy: () => void;
}

export function registerWorkspaceSwitcher(): void {
    Alpine.data('workspaceSwitcher', () => {
        return {
            open: false,
            search: '',
            selected: '',
            currentWorkspace: '',
            currentView: '',
            switchUrl: '',
            teamsDashboardUrl: '',
            isSwitching: false,
            searchTimeout: null as ReturnType<typeof setTimeout> | null,
            filteredWorkspaces: [] as Array<{ key: string; name: string }>,

            init(this: WorkspaceSwitcherData) {
                const el = this.$el;
                if (!el || !el.dataset) {
                    return;
                }

                this.currentWorkspace = el.dataset.currentWorkspace || '';
                this.currentView = el.dataset.currentView || '';
                this.switchUrl = el.dataset.switchUrl || '';
                this.teamsDashboardUrl = el.dataset.teamsDashboardUrl || '';
                this.selected = this.currentWorkspace;
                this.open = false;

                if (this.currentWorkspace && !VALID_WORKSPACE_KEY_PATTERN.test(this.currentWorkspace)) {
                    this.currentWorkspace = '';
                }

                if (typeof this.$watch === 'function') {
                    this.$watch('open', (value: unknown) => {
                        const isOpen = value as boolean;
                        this.updateBodyClass(isOpen);

                        if (isOpen && this.$nextTick) {
                            this.$nextTick(() => {
                                const searchInput = el.querySelector('.workspace-search-input') as HTMLInputElement;
                                if (searchInput) {
                                    searchInput.focus();
                                }
                            });
                        } else if (!isOpen) {
                            const triggerButton = el.querySelector('.sidebar-workspace-trigger') as HTMLButtonElement;
                            if (triggerButton) {
                                triggerButton.focus();
                            }
                        }
                    });
                }

                this.updateFilteredWorkspaces();
            },

            updateFilteredWorkspaces(this: WorkspaceSwitcherData): void {
                const el = this.$el;
                const workspaceOptions = el.querySelectorAll('.workspace-option');
                this.filteredWorkspaces = Array.from(workspaceOptions).map((option) => {
                    const key = option.getAttribute('data-workspace-key') || '';
                    const name = option.querySelector('.workspace-option-name')?.textContent?.trim() || '';
                    return { key, name };
                });
            },

            debouncedSearch(this: WorkspaceSwitcherData): void {
                if (this.searchTimeout) {
                    clearTimeout(this.searchTimeout);
                }
                this.searchTimeout = setTimeout(() => {
                }, SEARCH_DEBOUNCE_MS);
            },

            isVisible(this: WorkspaceSwitcherData, name: string): boolean {
                if (!this.search) return true;
                const searchLower = this.search.toLowerCase().trim();
                if (!searchLower) return true;
                return name.toLowerCase().includes(searchLower);
            },

            toggleModal(this: WorkspaceSwitcherData): void {
                if (this.isSwitching) return;
                this.open = !this.open;
                if (!this.open) {
                    this.selected = this.currentWorkspace;
                    this.search = '';
                }
                this.updateBodyClass();
            },

            closeModal(this: WorkspaceSwitcherData): void {
                if (this.isSwitching) return;
                this.open = false;
                this.selected = this.currentWorkspace;
                this.search = '';
                this.updateBodyClass();
            },

            handleKeydown(this: WorkspaceSwitcherData, event: KeyboardEvent): void {
                if (!this.open) return;

                const el = this.$el;
                const workspaceOptions = Array.from(
                    el.querySelectorAll('.workspace-option:not([style*="display: none"])')
                ) as HTMLElement[];

                if (workspaceOptions.length === 0) return;

                const currentIndex = workspaceOptions.findIndex(
                    (option) => option.getAttribute('data-workspace-key') === this.selected
                );

                let targetIndex = -1;

                switch (event.key) {
                    case 'ArrowDown':
                        event.preventDefault();
                        targetIndex = currentIndex < workspaceOptions.length - 1 ? currentIndex + 1 : 0;
                        break;
                    case 'ArrowUp':
                        event.preventDefault();
                        targetIndex = currentIndex > 0 ? currentIndex - 1 : workspaceOptions.length - 1;
                        break;
                    case 'Enter':
                        event.preventDefault();
                        if (this.selected && this.selected !== this.currentWorkspace) {
                            this.switchWorkspace();
                        }
                        return;
                    case 'Escape':
                        event.preventDefault();
                        this.closeModal();
                        return;
                    default:
                        return;
                }

                if (targetIndex >= 0 && targetIndex < workspaceOptions.length) {
                    const targetKey = workspaceOptions[targetIndex].getAttribute('data-workspace-key');
                    if (targetKey && VALID_WORKSPACE_KEY_PATTERN.test(targetKey)) {
                        this.selected = targetKey;
                        workspaceOptions[targetIndex].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                    }
                }
            },

            updateBodyClass(this: WorkspaceSwitcherData, openState?: boolean): void {
                const isOpen = typeof openState === 'boolean' ? openState : this.open;
                if (isOpen) {
                    document.body.classList.add('workspace-modal-open');
                } else {
                    document.body.classList.remove('workspace-modal-open');
                }
            },

            switchWorkspace(this: WorkspaceSwitcherData): void {
                if (this.isSwitching) return;

                if (!this.selected || this.selected === this.currentWorkspace) {
                    return;
                }

                if (!VALID_WORKSPACE_KEY_PATTERN.test(this.selected)) {
                    return;
                }

                if (!this.switchUrl) {
                    return;
                }

                this.isSwitching = true;

                const nextParam = this.currentView ? encodeURIComponent(this.currentView) : '';
                const targetUrl = `${this.switchUrl}${this.selected}/${nextParam ? `?next=${nextParam}` : ''}`;

                try {
                    window.location.href = targetUrl;
                } catch {
                    this.isSwitching = false;
                }
            },

            openNewWorkspaceModal(this: WorkspaceSwitcherData): void {
                if (this.isSwitching) return;

                this.closeModal();

                setTimeout(() => {
                    const addModal = document.getElementById('add-workspace-modal');
                    if (addModal) {
                        try {
                            const modalInstance = Modal.getOrCreateInstance(addModal);
                            modalInstance.show();
                        } catch {
                            if (this.teamsDashboardUrl) {
                                window.location.href = this.teamsDashboardUrl;
                            }
                        }
                    } else {
                        if (this.teamsDashboardUrl) {
                            window.location.href = this.teamsDashboardUrl;
                        }
                    }
                }, MODAL_TRANSITION_DELAY_MS);
            },

            destroy(this: WorkspaceSwitcherData) {
                if (this.searchTimeout) {
                    clearTimeout(this.searchTimeout);
                    this.searchTimeout = null;
                }
                document.body.classList.remove('workspace-modal-open');
                this.isSwitching = false;
            }
        };
    });
}
