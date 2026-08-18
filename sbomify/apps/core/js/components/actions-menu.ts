/** Gap between the trigger and the menu it opens, in px. */
const MENU_GAP = 8;
/** Margin the menu keeps from the viewport edge when it has to shift, in px. */
const VIEWPORT_MARGIN = 8;

export interface AnchorRect {
    top: number;
    bottom: number;
    right: number;
}

export interface Viewport {
    width: number;
    height: number;
}

/**
 * Where to put a menu of `menuHeight` opened from `anchor`.
 *
 * Right-aligned to the trigger via `right` rather than `left`, so the menu's own
 * width never has to be measured. Vertically it prefers to hang below; when the
 * space below cannot hold it and there is more above, it flips and anchors its
 * bottom edge to the trigger's top — which needs no height either, and is what
 * keeps a menu on the last row of a long table on screen.
 */
export function menuPosition(anchor: AnchorRect, menuHeight: number, viewport: Viewport): string {
    const right = Math.max(VIEWPORT_MARGIN, viewport.width - anchor.right);
    const spaceBelow = viewport.height - anchor.bottom;
    const spaceAbove = anchor.top;
    const flip = spaceBelow < menuHeight + MENU_GAP && spaceAbove > spaceBelow;

    return flip
        ? `right: ${right}px; bottom: ${viewport.height - anchor.top + MENU_GAP}px;`
        : `right: ${right}px; top: ${anchor.bottom + MENU_GAP}px;`;
}

/** The component's own state plus the `$refs` Alpine injects. */
interface MenuScope {
    open: boolean;
    style: string;
    dismiss: (() => void) | undefined;
    $refs: Record<string, HTMLElement | undefined>;
    position(): void;
    show(): void;
    close(): void;
}

/**
 * The row and header actions menu ("meatball") behind `components/tw/actions_menu.html.j2`.
 *
 * The menu is teleported to the body, because the tables that need one scroll
 * horizontally and would clip a menu positioned inside them. Teleporting means
 * fixed positioning, which does not follow a scrolling ancestor — so a scroll
 * anywhere closes the menu rather than leaving it stranded beside another row.
 */
export function actionsMenu() {
    return {
        open: false,
        /** Inline `right`/`top` offsets, recomputed each time the menu opens. */
        style: '',
        dismiss: undefined as (() => void) | undefined,

        init(this: MenuScope) {
            this.dismiss = () => this.close();
            // Capture phase: scroll does not bubble, so a listener on window
            // only sees the table's own scrolling this way.
            window.addEventListener('scroll', this.dismiss, true);
            window.addEventListener('resize', this.dismiss);
        },

        destroy(this: MenuScope) {
            if (!this.dismiss) return;
            window.removeEventListener('scroll', this.dismiss, true);
            window.removeEventListener('resize', this.dismiss);
        },

        toggle(this: MenuScope) {
            if (this.open) {
                this.close();
            } else {
                this.show();
            }
        },

        show(this: MenuScope) {
            // Hidden for the tick it takes to lay the menu out: it has to be
            // displayed before it can be measured, and an unpositioned menu
            // would otherwise appear at the top of the page for that tick.
            //
            // A bare timeout, not $nextTick (whose callback does not fire from
            // inside an Alpine.data method) and not requestAnimationFrame
            // (which never fires while the tab is hidden, so a menu opened in a
            // background tab would stay invisible). This runs after Alpine's
            // reactive flush has applied x-show, and measuring forces the
            // layout it needs, so there is nothing to wait for a paint for.
            this.style = 'visibility: hidden;';
            this.open = true;
            setTimeout(() => this.position());
        },

        position(this: MenuScope) {
            const trigger = this.$refs.trigger;
            const menu = this.$refs.menu;
            if (!trigger || !menu) return;
            this.style = menuPosition(trigger.getBoundingClientRect(), menu.offsetHeight, {
                width: window.innerWidth,
                height: window.innerHeight,
            });
        },

        close(this: MenuScope) {
            this.open = false;
        },

        /** Escape returns focus to the trigger, but only for the open menu. */
        closeAndFocus(this: MenuScope) {
            if (!this.open) return;
            this.close();
            this.$refs.trigger?.focus();
        },
    };
}
