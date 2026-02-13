
import { parseJsonScript, formatRelativeDate } from '../utils';
import { showSuccess, showError } from '../alerts-global';

interface AccessToken {
    id: string;
    description: string;
    created_at: string;
}

export function registerAccessTokensList() {
    if (window.Alpine) {
        window.Alpine.data('accessTokensList', (config: { tokensDataElementId: string, csrfToken: string }) => ({
            tokens: [] as AccessToken[],
            csrfToken: '',
            showDeleteModal: false,
            tokenToDelete: null as AccessToken | null,
            isDeleting: false,

            init() {
                if (!config.csrfToken || !config.csrfToken.trim()) {
                    return;
                }
                this.csrfToken = config.csrfToken;
                this.loadTokens();
            },

            loadTokens() {
                try {
                    const rawData = parseJsonScript(config.tokensDataElementId);
                    if (Array.isArray(rawData)) {
                        this.tokens = rawData as AccessToken[];
                    }
                } catch {
                    this.tokens = [];
                }
            },

            confirmDelete(token: AccessToken) {
                this.tokenToDelete = token;
                this.showDeleteModal = true;
            },

            async deleteToken() {
                if (!this.tokenToDelete || this.isDeleting) return;

                this.isDeleting = true;
                try {
                    const response = await fetch(`/access_tokens/${this.tokenToDelete.id}/delete`, {
                        method: 'DELETE',
                        headers: {
                            'X-CSRFToken': this.csrfToken,
                            'Content-Type': 'application/json'
                        }
                    });

                    if (response.ok) {
                        this.tokens = this.tokens.filter(t => t.id !== this.tokenToDelete!.id);
                        showSuccess('Access token deleted successfully');
                        this.showDeleteModal = false;
                        this.tokenToDelete = null;
                    } else {
                        // Parse error response
                        let errorMessage = 'Failed to delete token';
                        try {
                            const contentType = response.headers.get('Content-Type') || '';
                            if (contentType.includes('application/json')) {
                                const data = await response.json();
                                errorMessage = data.detail || data.message || errorMessage;
                            } else {
                                const text = await response.text();
                                if (text && text.trim()) errorMessage = text;
                            }
                        } catch {
                            // Failed to parse error response, use default message
                        }

                        // Provide context-specific messages
                        if (response.status === 403) {
                            errorMessage = 'You do not have permission to delete this token';
                        } else if (response.status === 404) {
                            errorMessage = 'Token not found';
                        } else if (response.status === 500) {
                            errorMessage = 'Server error. Please try again later.';
                        }

                        showError(errorMessage);
                    }
                } catch {
                    showError('An error occurred while deleting the token');
                } finally {
                    this.isDeleting = false;
                }
            },

            formatDate(dateString: string): string {
                return formatRelativeDate(dateString);
            }
        }));
    }
}
