import Alpine from 'alpinejs';

interface Notification {
    id: string;
    type: string;
    message: string;
    action_url?: string;
    severity: 'info' | 'warning' | 'error';
    created_at: string;
}

interface NotificationsModalData {
    notifications: Notification[];
    loading: boolean;
    error: string | null;
    refreshInterval: ReturnType<typeof setInterval> | null;
    $el: HTMLElement;
    $refs: { dialog?: HTMLElement };
    updateBadge: () => void;
    init: () => void;
    fetchNotifications: () => Promise<void>;
    clearAll: () => Promise<void>;
    formatDate: (dateString: string) => string;
    getSeverityIcon: (severity: string) => string;
    getSeverityBgColor: (severity: string) => string;
    destroy: () => void;
    handleOpenChange?: (this: NotificationsModalData & { open: boolean }) => void;
}

const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

function getCsrfToken(): string {
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1] || '';
    return cookieValue;
}

export function registerNotificationsModal(): void {
    Alpine.data('notificationsModal', (): NotificationsModalData & { open: boolean } => {
        return {
            notifications: [],
            loading: true,
            error: null,
            refreshInterval: null,
            open: false,
            $el: {} as HTMLElement, // Will be set by Alpine
            $refs: {} as { dialog?: HTMLElement },

            handleOpenChange(this: NotificationsModalData & { open: boolean }): void {
                const modal = this.$el;
                const modalDialog = (this.$refs as { dialog?: HTMLElement }).dialog;
                
                // Update aria-hidden immediately when state changes
                // This must happen before any focus operations
                modal.setAttribute('aria-hidden', this.open ? 'false' : 'true');
                
                if (this.open) {
                    this.fetchNotifications();
                    if (modalDialog) {
                        requestAnimationFrame(() => {
                            requestAnimationFrame(() => {
                                modalDialog.style.transform = 'translateX(0)';
                            });
                        });
                    }
                } else {
                    if (modalDialog) {
                        modalDialog.style.transform = 'translateX(100%)';
                    }
                }
            },

            init(this: NotificationsModalData & { open: boolean }) {
                // Use $el (the modal element) instead of getElementById
                const modal = this.$el;
                
                // Initialize aria-hidden based on initial open state
                modal.setAttribute('aria-hidden', this.open ? 'false' : 'true');
                
                // Use x-ref for modal dialog (already defined in template)
                const modalDialog = (this.$refs as { dialog?: HTMLElement }).dialog;
                if (modalDialog) {
                    const navbar = document.querySelector('.navbar') as HTMLElement | null;
                    const headerHeight = navbar ? navbar.offsetHeight : 60;
                    
                    modalDialog.style.position = 'fixed';
                    modalDialog.style.top = `${headerHeight}px`;
                    modalDialog.style.right = '0';
                    modalDialog.style.bottom = '0';
                    modalDialog.style.left = 'auto';
                    modalDialog.style.width = '320px';
                    modalDialog.style.maxWidth = '90vw';
                    modalDialog.style.margin = '0';
                    modalDialog.style.maxHeight = `calc(100vh - ${headerHeight}px)`;
                    modalDialog.style.transform = 'translateX(100%)';
                    modalDialog.style.transition = 'transform 0.3s ease-out';
                }

                // Watch for open state changes - using x-effect in template instead
                // Effect logic moved to template: x-effect="open; handleOpenChange()"

                // Listen for open-modal event
                modal.addEventListener('open-modal', ((event: CustomEvent) => {
                    if (event.detail.id === 'notificationsModal') {
                        this.open = true;
                    }
                }) as EventListener);

                // Initial fetch to update badge
                this.fetchNotifications();
                
                // Set up periodic refresh
                this.refreshInterval = setInterval(() => {
                    if (this.open) {
                        this.fetchNotifications();
                    }
                }, REFRESH_INTERVAL_MS);
            },

            async fetchNotifications(this: NotificationsModalData): Promise<void> {
                this.loading = true;
                this.error = null;

                try {
                    const response = await fetch('/api/v1/notifications/', {
                        method: 'GET',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                    });

                    if (!response.ok) {
                        throw new Error(`Failed to fetch notifications: ${response.status}`);
                    }

                    const data = await response.json();
                    this.notifications = Array.isArray(data) ? data : [];
                    this.loading = false;
                    this.updateBadge();
                } catch (error) {
                    console.error('Error fetching notifications:', error);
                    this.error = 'Failed to load notifications. Please try again.';
                    this.loading = false;
                }
            },

            updateBadge(this: NotificationsModalData): void {
                // Note: badge is outside component scope (in topnav), use querySelector
                const badge = document.getElementById('notifications-badge');
                const badgeCount = badge?.querySelector('.notifications-count');
                
                if (this.notifications.length === 0) {
                    if (badge) badge.style.display = 'none';
                } else {
                    if (badge) badge.style.display = 'block';
                    if (badgeCount) badgeCount.textContent = this.notifications.length.toString();
                }
            },

            async clearAll(this: NotificationsModalData): Promise<void> {
                try {
                    const response = await fetch('/api/v1/notifications/clear/', {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'X-CSRFToken': getCsrfToken(),
                        },
                    });

                    if (response.ok) {
                        await this.fetchNotifications();
                    } else {
                        console.error('Failed to clear notifications');
                    }
                } catch (error) {
                    console.error('Error clearing notifications:', error);
                }
            },

            formatDate(this: NotificationsModalData, dateString: string): string {
                const date = new Date(dateString);
                const now = new Date();
                const diffMs = now.getTime() - date.getTime();
                const diffMins = Math.floor(diffMs / 60000);
                const diffHours = Math.floor(diffMs / 3600000);
                const diffDays = Math.floor(diffMs / 86400000);

                if (diffMins < 1) {
                    return 'Just now';
                } else if (diffMins < 60) {
                    return `${diffMins} minute${diffMins > 1 ? 's' : ''} ago`;
                } else if (diffHours < 24) {
                    return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
                } else if (diffDays < 7) {
                    return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
                } else {
                    return date.toLocaleDateString();
                }
            },

            getSeverityIcon(this: NotificationsModalData, severity: string): string {
                switch (severity) {
                    case 'error':
                        return 'fas fa-exclamation-circle text-danger';
                    case 'warning':
                        return 'fas fa-exclamation-triangle text-warning';
                    case 'info':
                        return 'fas fa-info-circle text-info';
                    default:
                        return 'fas fa-bell text-secondary';
                }
            },

            getSeverityBgColor(this: NotificationsModalData, severity: string): string {
                switch (severity) {
                    case 'error':
                        return 'bg-danger-subtle';
                    case 'warning':
                        return 'bg-warning-subtle';
                    case 'info':
                        return 'bg-info-subtle';
                    default:
                        return 'bg-secondary-subtle';
                }
            },

            destroy(this: NotificationsModalData): void {
                if (this.refreshInterval) {
                    clearInterval(this.refreshInterval);
                    this.refreshInterval = null;
                }
            }
        };
    });
}
