import Alpine from 'alpinejs';
import $axios from '../utils';
import { showError, showWarning, showInfo, showConfirmation } from '../alerts';

// Fallback polling when WebSocket is not available
const FALLBACK_POLLING_INTERVAL_MS = 10 * 60 * 1000; // 10 minutes (longer since WS should handle most cases)
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
        baseIntervalMs: FALLBACK_POLLING_INTERVAL_MS,
        maxIntervalMs: MAX_POLLING_INTERVAL_MS,
        wsEventHandler: null as ((event: Event) => void) | null,
        wsConnectedHandler: null as (() => void) | null,
        wsDisconnectedHandler: null as (() => void) | null,

        init() {
            // Fetch notifications on initial load
            this.fetchNotifications(true);

            // Set up WebSocket listener for real-time notifications
            this.setupWebSocketListener();

            // Set up listener to stop polling when WebSocket connects
            this.setupWebSocketConnectionListener();

            // Fallback polling for when WebSocket is not available
            // This runs at a longer interval since WebSocket should handle most real-time updates
            this.intervalId = setInterval(() => {
                // Only poll if WebSocket is not connected
                const wsStore = Alpine.store('ws') as { connected?: boolean } | undefined;
                if (!wsStore?.connected) {
                    this.fetchNotifications(false);
                }
            }, this.baseIntervalMs);
        },

        setupWebSocketConnectionListener() {
            // Stop fallback polling when WebSocket connects to avoid unnecessary API calls
            this.wsConnectedHandler = () => {
                if (this.intervalId !== null) {
                    clearInterval(this.intervalId);
                    this.intervalId = null;
                }
            };
            window.addEventListener('ws:connected', this.wsConnectedHandler);

            // Restart fallback polling when WebSocket disconnects so notifications continue to be fetched
            this.wsDisconnectedHandler = () => {
                // Only start polling if it's not already running
                if (this.intervalId === null) {
                    this.intervalId = setInterval(() => {
                        // Only poll if WebSocket is not connected
                        const wsStore = Alpine.store('ws') as { connected?: boolean } | undefined;
                        if (!wsStore?.connected) {
                            this.fetchNotifications(false);
                        }
                    }, this.baseIntervalMs);
                }
            };
            window.addEventListener('ws:disconnected', this.wsDisconnectedHandler);
        },

        setupWebSocketListener() {
            // Listen for notification events from WebSocket
            this.wsEventHandler = (event: Event) => {
                const customEvent = event as CustomEvent;
                const data = customEvent.detail;

                // Defensive check for valid notification data
                if (!data || data.type !== 'notification') {
                    return;
                }

                // Handle notification pushed via WebSocket
                const notification: Notification = {
                    id: data.id || `ws-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
                    type: data.notification_type || 'info',
                    message: data.message,
                    action_url: data.action_url,
                    severity: data.severity || 'info',
                    created_at: data.created_at || new Date().toISOString(),
                };

                // Process the notification if not already processed
                if (!this.processedNotifications.has(notification.id)) {
                    this.notifications.push(notification);
                    this.processNotifications([notification], false);
                }
            };

            window.addEventListener('ws:message', this.wsEventHandler);
        },

        destroy() {
            if (this.intervalId !== null) {
                clearInterval(this.intervalId);
                this.intervalId = null;
            }

            if (this.wsEventHandler) {
                window.removeEventListener('ws:message', this.wsEventHandler);
                this.wsEventHandler = null;
            }

            if (this.wsConnectedHandler) {
                window.removeEventListener('ws:connected', this.wsConnectedHandler);
                this.wsConnectedHandler = null;
            }

            if (this.wsDisconnectedHandler) {
                window.removeEventListener('ws:disconnected', this.wsDisconnectedHandler);
                this.wsDisconnectedHandler = null;
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
                    showConfirmation({
                        title: notification.severity.charAt(0).toUpperCase() + notification.severity.slice(1),
                        message: notification.message,
                        type: notification.severity === 'error' ? 'danger' : notification.severity,
                        confirmText: 'Take Action',
                        cancelText: 'Dismiss',
                    }).then((confirmed: boolean) => {
                        if (confirmed && notification.action_url) {
                            window.location.href = notification.action_url;
                        }
                    });
                } else {
                    showAlert(notification.message);
                }
            });
        }
    }));
}

