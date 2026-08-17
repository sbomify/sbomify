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

// How long a socket must stay open before the attempt budget is refunded.
//
// A completed handshake is not success. The server accepts the handshake
// before it applies its verdict, precisely so it can answer with a close code
// the browser can read, which means `onopen` fires on rejected connections
// too. Refunding the budget there made every rejection look like a fresh
// start: the delay was recomputed from attempt zero and the cap was never
// reached, so a broker outage turned into one reconnect per second per tab
// against an already-degraded server.
//
// Long enough to outlast an immediate accept-then-close, short enough that a
// genuinely working socket is credited well before the next drop.
const CONNECTION_STABLE_AFTER_MS = 5000;

// Terminal verdicts about this client: policy violation (auth), protocol
// error, unsupported data. Retrying these replays the same rejection.
const NO_RETRY_CLOSE_CODES = new Set([1002, 1003, 1008]);

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
    stableTimer: ReturnType<typeof setTimeout> | null;
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
        stableTimer: null,
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

            this.openSocket(workspaceKey);
        },

        /**
         * Open a socket without tearing down retry state.
         *
         * Retries route here rather than through connect(), which resets the
         * attempt counter as part of its deliberate-disconnect semantics. Going
         * through connect() zeroed the counter on every retry, so the backoff
         * never grew past its first step and the attempt budget was never spent.
         */
        openSocket(workspaceKey: string): void {
            const state = this as unknown as WebSocketStoreState;

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
                    state.lastError = null;

                    // Budget refunded only once the socket has held open, not
                    // here: see CONNECTION_STABLE_AFTER_MS. onclose clears this
                    // timer, so a socket closed before it fires — every
                    // server-side rejection — keeps its place in the backoff.
                    if (state.stableTimer) {
                        clearTimeout(state.stableTimer);
                    }
                    state.stableTimer = setTimeout(() => {
                        state.reconnectAttempts = 0;
                        state.stableTimer = null;
                    }, CONNECTION_STABLE_AFTER_MS);

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
                    state.connected = false;
                    state.connecting = false;
                    state.socket = null;

                    // A socket that closed before it was credited never proves
                    // anything, so it must not refund the budget after the fact.
                    if (state.stableTimer) {
                        clearTimeout(state.stableTimer);
                        state.stableTimer = null;
                    }

                    // Dispatch disconnection event
                    window.dispatchEvent(new CustomEvent('ws:disconnected', {
                        detail: {
                            workspaceKey: state.workspaceKey,
                            code: event.code,
                            reason: event.reason,
                            wasClean: event.wasClean
                        }
                    }));

                    // Every close that reaches this handler is the server's or
                    // the network's doing — disconnect() detaches handlers
                    // before closing. That includes wasClean closes: uvicorn
                    // sends a clean 1012 (service restart, "please retry") on
                    // shutdown, so gating on wasClean (or on having been
                    // connected before, which a refused handshake never was)
                    // left tabs permanently silent after each deploy.
                    if (state.workspaceKey && !NO_RETRY_CLOSE_CODES.has(event.code)) {
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

            // A deliberate disconnect resets the budget outright below, so a
            // pending credit would only fire against the next socket.
            if (state.stableTimer) {
                clearTimeout(state.stableTimer);
                state.stableTimer = null;
            }

            if (state.socket) {
                // Detach first: the close event arrives asynchronously, and a
                // stale handler firing after connect() has installed a new
                // socket would null it out and mark the live connection down.
                state.socket.onopen = null;
                state.socket.onmessage = null;
                state.socket.onclose = null;
                state.socket.onerror = null;
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

            // The budget now genuinely runs out, which it never did before, so
            // a tab that sleeps through all ten attempts stays silent. Retrying
            // on visibilitychange is the upgrade if that turns up in practice.
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
                    this.openSocket(state.workspaceKey);
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
        openSocket: (workspaceKey: string) => void;
        disconnect: () => void;
        scheduleReconnect: () => void;
        isReady: () => boolean;
    });
}

export default { registerWebSocketStore };
