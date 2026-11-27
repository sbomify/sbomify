import { showSuccess, showError } from '../alerts';
import { getCsrfToken as getCsrfTokenFromModule } from '../csrf';

interface DeleteModalConfig {
    modalId: string;
    hxUrl: string;
    hxMethod?: string;
    successMessage: string;
    csrfToken: string;
    redirectUrl?: string;
    refreshEvent?: string;
}

interface DeleteModalData {
    isLoading: boolean;
    getCsrfToken(): string;
    handleDelete(): Promise<void>;
    [key: string]: boolean | (() => string) | (() => Promise<void>);
}

interface BulkRevokeConfig {
    url: string;
    csrfToken?: string;
    refreshEvent?: string;
}

interface BulkRevokeData {
    selected: number[];
    showBulkModal: boolean;
    showRevokeAllModal: boolean;
    isLoading: boolean;
    readonly countLabel: string;
    getCsrfToken(): string;
    toggleAll(checked: boolean, ids: number[]): void;
    revokeSelected(): Promise<void>;
    revokeAll(): Promise<void>;
    _revoke(body: Record<string, unknown>, label: string, modalKey: 'showBulkModal' | 'showRevokeAllModal'): Promise<void>;
}

declare global {
    interface Window {
        getDeleteModalData: (config: DeleteModalConfig) => DeleteModalData;
        getBulkRevokeData: (config: BulkRevokeConfig) => BulkRevokeData;
    }
}

export function registerDeleteModal() {
    if (!window.getDeleteModalData) {
        window.getDeleteModalData = function (config: DeleteModalConfig) {
            return {
                isLoading: false,
                getCsrfToken() {
                    // Priority 1: Use token passed from Django template
                    if (config.csrfToken && config.csrfToken.trim()) {
                        return config.csrfToken.trim();
                    }

                    // Priority 2: Use centralized CSRF token module
                    try {
                        return getCsrfTokenFromModule();
                    } catch {
                        return '';
                    }
                },
                async handleDelete() {
                    if (this.isLoading) return;
                    this.isLoading = true;

                    const csrfToken = this.getCsrfToken();

                    if (!csrfToken) {
                        this.isLoading = false;
                        showError('Security error: Missing CSRF token. Please reload the page and try again.');
                        this[config.modalId] = false;
                        return;
                    }

                    try {
                        const response = await fetch(config.hxUrl, {
                            method: config.hxMethod || 'DELETE',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': csrfToken
                            },
                            credentials: 'same-origin'
                        });

                        if (response.ok) {
                            showSuccess(config.successMessage); // Use imported function
                            this[config.modalId] = false;
                            if (config.redirectUrl) {
                                window.location.href = config.redirectUrl;
                            } else if (config.refreshEvent) {
                                // Dispatch custom event to trigger HTMX refresh
                                document.body.dispatchEvent(new CustomEvent(config.refreshEvent));
                            }
                        } else {
                            let errorDetail = '';
                            try {
                                const contentType = response.headers.get('Content-Type') || '';

                                if (contentType.includes('application/json')) {
                                    const data = await response.json() as { detail?: string } | Record<string, unknown>;
                                    if (data) {
                                        if (typeof data.detail === 'string') {
                                            errorDetail = data.detail;
                                        } else {
                                            errorDetail = JSON.stringify(data);
                                        }
                                    }
                                } else {
                                    errorDetail = await response.text();
                                }
                            } catch {
                                // Failed to parse error response
                            }

                            if (errorDetail) {
                                showError(`Failed to delete: ${errorDetail}`);
                            } else {
                                showError('Failed to delete. Please try again.');
                            }
                            this[config.modalId] = false;
                        }
                    } catch {
                        showError('An error occurred. Please try again.');
                        this[config.modalId] = false;
                    } finally {
                        this.isLoading = false;
                    }
                }
            };
        };
    }

    // Bulk token revocation (#1061): one Alpine component over the whole token list.
    if (!window.getBulkRevokeData) {
        window.getBulkRevokeData = function (config: BulkRevokeConfig): BulkRevokeData {
            return {
                selected: [],
                showBulkModal: false,
                showRevokeAllModal: false,
                isLoading: false,
                get countLabel(): string {
                    const n = this.selected.length;
                    return `${n} token${n === 1 ? '' : 's'}`;
                },
                getCsrfToken(): string {
                    if (config.csrfToken && config.csrfToken.trim()) {
                        return config.csrfToken.trim();
                    }
                    try {
                        return getCsrfTokenFromModule();
                    } catch {
                        return '';
                    }
                },
                toggleAll(checked: boolean, ids: number[]): void {
                    this.selected = checked ? [...ids] : [];
                },
                async revokeSelected(): Promise<void> {
                    if (this.selected.length === 0) return;
                    await this._revoke({ token_ids: this.selected }, this.countLabel, 'showBulkModal');
                },
                async revokeAll(): Promise<void> {
                    await this._revoke({ all: true }, 'all tokens', 'showRevokeAllModal');
                },
                async _revoke(body, label, modalKey): Promise<void> {
                    if (this.isLoading) return;
                    this.isLoading = true;
                    const csrfToken = this.getCsrfToken();
                    if (!csrfToken) {
                        this.isLoading = false;
                        showError('Security error: Missing CSRF token. Please reload the page and try again.');
                        this[modalKey] = false;
                        return;
                    }
                    try {
                        const response = await fetch(config.url, {
                            method: 'DELETE',
                            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                            credentials: 'same-origin',
                            body: JSON.stringify(body),
                        });
                        if (response.ok) {
                            showSuccess(`Revoked ${label}`);
                            this[modalKey] = false;
                            this.selected = [];
                            if (config.refreshEvent) {
                                document.body.dispatchEvent(new CustomEvent(config.refreshEvent));
                            }
                        } else {
                            let detail = 'Failed to revoke the selected tokens.';
                            try {
                                if ((response.headers.get('Content-Type') || '').includes('application/json')) {
                                    const data = (await response.json()) as { detail?: string };
                                    if (data?.detail) detail = data.detail;
                                }
                            } catch {
                                // Non-JSON / unparseable body — keep the default message.
                            }
                            showError(detail);
                        }
                    } catch {
                        showError('Network error while revoking tokens.');
                    } finally {
                        this.isLoading = false;
                    }
                },
            };
        };
    }
}
