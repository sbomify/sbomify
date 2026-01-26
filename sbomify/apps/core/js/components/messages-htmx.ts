import Alpine from 'alpinejs';
import { showToast } from '../alerts';

interface MessageData {
    messages?: Array<{ level_tag: string; message: string }>;
    pendingInvitationsCount?: number;
    pendingAccessRequestsCount?: number;
}

function showMessage(messageType: string, messageText: string): void {
    let type: 'error' | 'success' | 'warning' | 'info';
    switch (messageType) {
        case 'alert-danger':
        case 'error':
            type = 'error';
            break;
        case 'alert-success':
        case 'success':
            type = 'success';
            break;
        case 'alert-warning':
        case 'warning':
            type = 'warning';
            break;
        case 'alert-info':
        case 'info':
            type = 'info';
            break;
        default:
            type = 'info';
    }

    showToast({
        title: type.charAt(0).toUpperCase() + type.slice(1),
        message: messageText,
        type: type
    });
}

/**
 * Messages HTMX Component
 * Handles Django messages and notifications for HTMX pages
 * Reads data from x-ref script template
 */
export function registerMessagesHtmx(): void {
    Alpine.data('messagesHtmx', () => {
        return {
            messages: [] as Array<{ level_tag: string; message: string }>,
            pendingInvitationsCount: 0,
            pendingAccessRequestsCount: 0,
            // Use $persist with sessionStorage for tracking shown toasts
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            invitationToastShown: (Alpine as any).$persist(false)
                .as('session_invitation_toast_shown')
                .using(sessionStorage),
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            accessRequestToastShown: (Alpine as any).$persist(false)
                .as('session_access_request_toast_shown')
                .using(sessionStorage),

            messagesHandler: null as ((event: CustomEvent) => void) | null,

            init() {
                // Read data from x-ref script template
                try {
                    const dataElement = this.$refs.messagesHtmxData as HTMLElement;
                    if (dataElement && dataElement.textContent) {
                        const data = JSON.parse(dataElement.textContent.trim()) as MessageData;
                        this.messages = data.messages || [];
                        this.pendingInvitationsCount = data.pendingInvitationsCount || 0;
                        this.pendingAccessRequestsCount = data.pendingAccessRequestsCount || 0;
                    }
                } catch (error) {
                    console.error('Failed to parse messages HTMX data:', error);
                    this.messages = [];
                    this.pendingInvitationsCount = 0;
                    this.pendingAccessRequestsCount = 0;
                }
                // Show Django messages
                if (this.messages.length > 0) {
                    this.showMessagesWhenReady();
                }

                // Show invitation notification
                if (this.pendingInvitationsCount > 0) {
                    this.showInvitationNotification();
                }

                // Show access request notification
                if (this.pendingAccessRequestsCount > 0) {
                    this.showAccessRequestNotification();
                }

                // Listen for custom messages event
                this.messagesHandler = (event: CustomEvent) => {
                    if (!event.detail?.value || !Array.isArray(event.detail.value)) {
                        return;
                    }
                    event.detail.value.forEach((msg: { type: string; message: string }) => {
                        showMessage(msg.type, msg.message);
                    });
                };
                document.body.addEventListener('messages', this.messagesHandler as EventListener);
            },

            destroy() {
                // Remove event listener
                if (this.messagesHandler) {
                    document.body.removeEventListener('messages', this.messagesHandler as EventListener);
                    this.messagesHandler = null;
                }
            },

            showMessagesWhenReady() {
                // Show messages immediately - showToast is imported directly
                this.messages.forEach(msg => {
                    showMessage(msg.level_tag, msg.message);
                });
            },

            showInvitationNotification() {
                // Use $persist property instead of manual sessionStorage
                if (!this.invitationToastShown) {
                    const count = this.pendingInvitationsCount;
                    const message = count === 1
                        ? 'You have a workspace invitation! Check your settings to accept it.'
                        : `You have ${count} workspace invitations! Check your settings to accept them.`;

                    showToast({
                        title: 'Workspace Invitation',
                        message: message,
                        type: 'info'
                    });
                    this.invitationToastShown = true;
                }
            },

            showAccessRequestNotification() {
                // Use $persist property instead of manual sessionStorage
                if (!this.accessRequestToastShown) {
                    const count = this.pendingAccessRequestsCount;
                    const message = count === 1
                        ? 'You have a pending access request to review!'
                        : `You have ${count} pending access requests to review!`;

                    showToast({
                        title: 'Access Request',
                        message: message,
                        type: 'info'
                    });
                    this.accessRequestToastShown = true;
                }
            }
        };
    });
}
