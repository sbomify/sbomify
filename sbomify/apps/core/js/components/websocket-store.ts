/**
 * WebSocket Store for Alpine.js
 *
 * Provides real-time WebSocket connectivity for workspace-scoped updates.
 * This store manages the WebSocket connection and dispatches events for
 * components to react to.
 *
 * Usage:
 * - Initialize in template: x-init="$store.ws.connect('workspace-key')"
 * - Listen to events: @ws:message.window="handleMessage($event.detail)"
 * - Check connection: x-show="$store.ws.connected"
 */
import Alpine from 'alpinejs';

// Only log in development mode (Vite sets this)
const DEBUG = import.meta.env.DEV;

// Reconnection configuration
const RECONNECT_BASE_DELAY_MS = 1000; // Start with 1 second
const RECONNECT_MAX_DELAY_MS = 30000; // Max 30 seconds
const RECONNECT_MAX_ATTEMPTS = 10; // Give up after 10 attempts

interface WebSocketMessage {
    type: string;
    [key: string]: unknown;
}

interface WebSocketStoreState {
    socket: WebSocket | null;
    connected: boolean;
    connecting: boolean;
    workspaceKey: string | null;
    reconnectAttempts: number;
    reconnectTimer: ReturnType<typeof setTimeout> | null;
    lastError: string | null;
}

/**
 * Register the WebSocket store with Alpine.js
 */
export function registerWebSocketStore(): void {
    Alpine.store('ws', {
        socket: null,
        connected: false,
        connecting: false,
        workspaceKey: null,
        reconnectAttempts: 0,
        reconnectTimer: null,
        lastError: null,

        /**
         * Connect to the WebSocket server for a specific workspace.
         */
        connect(workspaceKey: string): void {
            const state = this as unknown as WebSocketStoreState;

            // Don't reconnect if already connected to the same workspace
            if (state.socket && state.workspaceKey === workspaceKey && state.connected) {
                return;
            }

            // Disconnect from any existing connection
            this.disconnect();

            state.workspaceKey = workspaceKey;
            state.connecting = true;
            state.lastError = null;

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/workspace/${workspaceKey}/`;

            try {
                state.socket = new WebSocket(wsUrl);

                state.socket.onopen = () => {
                    state.connected = true;
                    state.connecting = false;
                    state.reconnectAttempts = 0;
                    state.lastError = null;

                    // Dispatch connection event
                    window.dispatchEvent(new CustomEvent('ws:connected', {
                        detail: { workspaceKey }
                    }));
                };

                state.socket.onmessage = (event: MessageEvent) => {
                    try {
                        const data = JSON.parse(event.data) as WebSocketMessage;

                        // Dispatch a generic ws:message event
                        window.dispatchEvent(new CustomEvent('ws:message', {
                            detail: data
                        }));

                        // Also dispatch a specific event based on message type
                        if (data.type) {
                            window.dispatchEvent(new CustomEvent(`ws:${data.type}`, {
                                detail: data
                            }));
                        }
                    } catch (error) {
                        if (DEBUG) {
                            console.error('[WebSocket] Failed to parse message:', event.data, error);
                        }
                    }
                };

                state.socket.onclose = (event: CloseEvent) => {
                    const wasConnected = state.connected;
                    state.connected = false;
                    state.connecting = false;
                    state.socket = null;

                    // Dispatch disconnection event
                    window.dispatchEvent(new CustomEvent('ws:disconnected', {
                        detail: {
                            workspaceKey: state.workspaceKey,
                            code: event.code,
                            reason: event.reason,
                            wasClean: event.wasClean
                        }
                    }));

                    // Attempt reconnection if this wasn't a clean close
                    // and we were previously connected or trying to connect
                    if (!event.wasClean && wasConnected && state.workspaceKey) {
                        this.scheduleReconnect();
                    }
                };

                state.socket.onerror = () => {
                    state.lastError = 'Connection error';
                    // onclose will be called after onerror
                };

            } catch (error) {
                state.connecting = false;
                state.lastError = error instanceof Error ? error.message : 'Connection failed';
                if (DEBUG) {
                    console.error('[WebSocket] Connection error:', error);
                }
                this.scheduleReconnect();
            }
        },

        /**
         * Disconnect from the WebSocket server.
         */
        disconnect(): void {
            const state = this as unknown as WebSocketStoreState;

            // Clear any pending reconnection
            if (state.reconnectTimer) {
                clearTimeout(state.reconnectTimer);
                state.reconnectTimer = null;
            }

            if (state.socket) {
                state.socket.close(1000, 'Client disconnect');
                state.socket = null;
            }

            state.connected = false;
            state.connecting = false;
            state.reconnectAttempts = 0;
        },

        /**
         * Schedule a reconnection attempt with exponential backoff.
         */
        scheduleReconnect(): void {
            const state = this as unknown as WebSocketStoreState;

            if (!state.workspaceKey) {
                return;
            }

            if (state.reconnectAttempts >= RECONNECT_MAX_ATTEMPTS) {
                state.lastError = 'Max reconnection attempts reached';
                if (DEBUG) {
                    console.warn('[WebSocket] Max reconnection attempts reached, giving up');
                }
                return;
            }

            // Exponential backoff with proportional jitter
            const baseDelay = RECONNECT_BASE_DELAY_MS * Math.pow(2, state.reconnectAttempts);
            const jitter = Math.random() * baseDelay * 0.1;
            const delay = Math.min(baseDelay + jitter, RECONNECT_MAX_DELAY_MS);

            state.reconnectAttempts++;

            state.reconnectTimer = setTimeout(() => {
                if (state.workspaceKey) {
                    this.connect(state.workspaceKey);
                }
            }, delay);
        },

        /**
         * Check if connected and ready to receive messages.
         */
        isReady(): boolean {
            const state = this as unknown as WebSocketStoreState;
            return state.connected && state.socket !== null && state.socket.readyState === WebSocket.OPEN;
        }
    } as WebSocketStoreState & {
        connect: (workspaceKey: string) => void;
        disconnect: () => void;
        scheduleReconnect: () => void;
        isReady: () => boolean;
    });
}

export default { registerWebSocketStore };
