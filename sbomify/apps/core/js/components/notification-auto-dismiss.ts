import Alpine from 'alpinejs';

/**
 * Notification Auto-Dismiss Component
 * Handles auto-dismiss for alerts with hover pause using Alpine.js
 * Replaces Bootstrap.Alert with pure Alpine state management
 */
export function registerNotificationAutoDismiss(): void {
    Alpine.data('notificationAutoDismiss', (timeout: number = 4000) => {
        return {
            timeout,
            timer: null as ReturnType<typeof setTimeout> | null,
            isVisible: true,
            
            init() {
                this.startTimer();
            },
            
            startTimer() {
                this.clearTimer();
                this.timer = setTimeout(() => {
                    this.dismiss();
                }, this.timeout);
            },
            
            clearTimer() {
                if (this.timer) {
                    clearTimeout(this.timer);
                    this.timer = null;
                }
            },
            
            dismiss() {
                this.isVisible = false;
                this.clearTimer();
                // Remove element after transition
                setTimeout(() => {
                    if (this.$el && this.$el.parentNode) {
                        this.$el.parentNode.removeChild(this.$el);
                    }
                }, 150);
            },
            
            handleMouseEnter() {
                this.clearTimer();
            },
            
            handleMouseLeave() {
                this.startTimer();
            },
            
            destroy() {
                // Cleanup timer when component is removed
                this.clearTimer();
            }
        };
    });
}
