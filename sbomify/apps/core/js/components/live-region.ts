/**
 * A region of a server-rendered page that follows workspace socket messages.
 *
 * The element carries its own htmx refresh (hx-get, hx-select, hx-swap and
 * hx-trigger="live-refresh"); this decides when to fire it. A matching update
 * refreshes the region after a short wait so a burst repaints once. A matching
 * delete leaves for `leaveTo`, since the page is about something that no longer
 * exists. A resync, sent when the socket reconnects, refreshes too.
 *
 * A refresh never lands under the reader's hands: while a field inside the
 * region has focus, as during an inline edit, it waits until focus leaves.
 * A focused button does not count, or a click would hold refreshes back
 * until the reader happened to click somewhere else.
 */

const EDITABLE = 'input, textarea, select, [contenteditable]';

interface LiveRegionOptions {
    /** Message types that mean the region's subject changed. */
    refresh: string[];
    /** Message types that mean the region's subject is gone. */
    remove?: string[];
    /** The payload field naming the subject, and its value on this page. */
    key: string;
    id: string;
    /** Where to go when the subject is deleted. */
    leaveTo?: string;
    /** Milliseconds to wait for a burst to settle. */
    wait?: number;
}

interface LiveMessage {
    type?: string;
    [field: string]: unknown;
}

/** Whether the reader is typing in a field inside this element. */
function editingWithin(el: HTMLElement): boolean {
    const active = document.activeElement;
    return Boolean(active && active.matches?.(EDITABLE) && el.contains(active));
}

interface LiveRegionScope {
    $el: HTMLElement;
    timer: ReturnType<typeof setTimeout> | null;
    due: boolean;
    options: Required<LiveRegionOptions>;
    fire: () => void;
    receive: (message: LiveMessage) => void;
}

const DEFAULT_WAIT_MS = 500;

export function liveRegion(options: LiveRegionOptions) {
    return {
        timer: null as ReturnType<typeof setTimeout> | null,
        due: false,
        options: { remove: [], leaveTo: '', wait: DEFAULT_WAIT_MS, ...options } as Required<LiveRegionOptions>,

        init(this: LiveRegionScope) {
            // A refresh held back during an edit runs once focus leaves.
            this.$el.addEventListener('focusout', () => {
                setTimeout(() => {
                    if (this.due && !editingWithin(this.$el)) this.fire();
                }, 0);
            });
            window.addEventListener('ws:message', (event: Event) => {
                this.receive((event as CustomEvent<LiveMessage>).detail ?? {});
            });
        },

        receive(this: LiveRegionScope, message: LiveMessage) {
            const { refresh, remove, key, id, leaveTo, wait } = this.options;
            const type = message.type ?? '';
            const aboutThis = message[key] === id;

            if (aboutThis && remove.includes(type) && leaveTo) {
                window.location.assign(leaveTo);
                return;
            }
            if (type !== 'resync' && !(aboutThis && refresh.includes(type))) return;

            if (this.timer) clearTimeout(this.timer);
            this.timer = setTimeout(() => {
                this.timer = null;
                this.due = true;
                if (!editingWithin(this.$el)) this.fire();
            }, wait);
        },

        fire(this: LiveRegionScope) {
            this.due = false;
            this.$el.dispatchEvent(new CustomEvent('live-refresh'));
        },
    };
}
