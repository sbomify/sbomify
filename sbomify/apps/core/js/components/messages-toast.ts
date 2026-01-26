import Alpine from 'alpinejs';

interface Message {
    level_tag: string;
    message: string;
}

interface MessagesToastData {
    messages: Message[];
    processed: boolean;
    $refs: { messagesData?: HTMLElement };
    $store?: { alerts?: { showToast: (options: { title: string; message: string; type: string }) => void } };
    processMessages(): void;
}

/**
 * Messages Toast Component
 * Handles Django messages and displays them as toasts
 * Reads data from x-ref script template
 */
export function registerMessagesToast(): void {
    Alpine.data('messagesToast', () => {
        return {
            messages: [] as Message[],
            processed: false,
            $refs: {} as { messagesData?: HTMLElement },
            $store: undefined as { alerts?: { showToast: (options: { title: string; message: string; type: string }) => void } } | undefined,
            
            init() {
                // Read data from x-ref script template
                try {
                    const dataElement = this.$refs.messagesData as HTMLElement;
                    if (dataElement && dataElement.textContent) {
                        this.messages = JSON.parse(dataElement.textContent.trim()) as Message[];
                    }
                } catch (error) {
                    console.error('Failed to parse messages data:', error);
                    this.messages = [];
                }
                
                if (this.messages.length > 0 && !this.processed) {
                    this.processMessages();
                }
            },
            
            processMessages() {
                if (this.processed) return;
                this.processed = true;
                
                // Use alerts store
                try {
                    const alertsStore = this.$store?.alerts;
                    if (!alertsStore) {
                        console.warn('Alerts store not available');
                        return;
                    }
                    
                    // Process each message
                    for (const message of this.messages) {
                        const type = message.level_tag === 'error' ? 'error' :
                            message.level_tag === 'success' ? 'success' :
                            message.level_tag === 'warning' ? 'warning' : 'info';
                        
                        alertsStore.showToast({
                            title: message.level_tag.charAt(0).toUpperCase() + message.level_tag.slice(1),
                            message: message.message,
                            type: type as 'success' | 'error' | 'warning' | 'info'
                        });
                    }
                } catch (err) {
                    console.error('Error showing messages:', err);
                }
            }
        } as MessagesToastData;
    });
}
