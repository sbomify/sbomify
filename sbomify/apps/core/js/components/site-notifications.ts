import Alpine from 'alpinejs';
import $axios from '../utils';
import { showError, showWarning, showInfo } from '../alerts';

const POLLING_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes
const MAX_POLLING_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes

interface Notification {
    id: string;
    type: string;
    message: string;
    action_url?: string;
    severity: 'info' | 'warning' | 'error';
    created_at: string;
}

export function registerSiteNotifications() {
    Alpine.data('siteNotifications', () => ({
        notifications: [] as Notification[],
        processedNotifications: new Set<string>(),
        intervalId: null as ReturnType<typeof setInterval> | null,
        consecutiveErrors: 0,
        baseIntervalMs: POLLING_INTERVAL_MS,
        maxIntervalMs: MAX_POLLING_INTERVAL_MS,

        init() {
            this.fetchNotifications(true);
            this.intervalId = setInterval(() => this.fetchNotifications(false), this.baseIntervalMs);
        },

        destroy() {
            if (this.intervalId !== null) {
                clearInterval(this.intervalId);
                this.intervalId = null;
            }
        },

        rescheduleWithBackoff() {
            if (this.intervalId !== null) {
                clearInterval(this.intervalId);
            }
            const backoffMs = Math.min(
                this.baseIntervalMs * Math.pow(2, this.consecutiveErrors),
                this.maxIntervalMs
            );
            this.intervalId = setInterval(() => this.fetchNotifications(false), backoffMs);
        },

        async fetchNotifications(isInitialLoad: boolean = false) {
            try {
                const response = await $axios.get('/api/v1/notifications/');
                const oldNotifications = [...this.notifications];
                this.notifications = response.data;
                this.consecutiveErrors = 0;

                if (!isInitialLoad) {
                    const newItems = this.notifications.filter(
                        (newItem: Notification) => !oldNotifications.some((oldItem: Notification) => oldItem.id === newItem.id)
                    );
                    if (newItems.length > 0) {
                        this.processNotifications(newItems, false);
                    }
                } else {
                    this.notifications.forEach((notification: Notification) => {
                        this.processedNotifications.add(notification.id);
                    });
                }
            } catch (error) {
                console.error('Failed to fetch notifications:', error);
                this.consecutiveErrors++;
                this.rescheduleWithBackoff();
            }
        },

        processNotifications(newNotifications: Notification[], isInitialLoad: boolean = false) {
            if (isInitialLoad) return;

            newNotifications.forEach((notification: Notification) => {
                if (this.processedNotifications.has(notification.id)) return;
                this.processedNotifications.add(notification.id);

                const showAlert = (message: string) => {
                    switch (notification.severity) {
                        case 'error':
                            return showError(message);
                        case 'warning':
                            return showWarning(message);
                        case 'info':
                            return showInfo(message);
                        default:
                            return showInfo(message);
                    }
                };

                if (notification.action_url) {
                    import('sweetalert2').then(({ default: Swal }) => {
                        Swal.fire({
                            title: notification.severity.charAt(0).toUpperCase() + notification.severity.slice(1),
                            text: notification.message,
                            icon: notification.severity,
                            showCancelButton: true,
                            confirmButtonText: 'Take Action',
                            cancelButtonText: 'Dismiss',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                                cancelButton: 'btn btn-secondary',
                                actions: 'gap-2'
                            },
                            buttonsStyling: false
                        }).then((result: { isConfirmed: boolean }) => {
                            if (result.isConfirmed && notification.action_url) {
                                window.location.href = notification.action_url;
                            }
                        });
                    });
                } else {
                    showAlert(notification.message);
                }
            });
        }
    }));
}

