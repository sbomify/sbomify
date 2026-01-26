import Alpine from 'alpinejs';

interface SidebarData {
    open: boolean;
    touchStartX: number;
    touchEndX: number;
    $el: HTMLElement;
    $store?: {
        sidebar?: {
            open: boolean;
            toggle(): void;
            close(): void;
        };
    };
    $watch?: (property: string, callback: (value: unknown) => void) => void;
    $nextTick?: (callback: () => void) => void;
    init: () => void;
    toggle: () => void;
    close: () => void;
    handleStoreChange: () => void;
    handleSwipe: () => void;
    handleKeydown: (event: KeyboardEvent) => void;
    handleResize: () => void;
    handleTouchStart: (event: TouchEvent) => void;
    handleTouchEnd: (event: TouchEvent) => void;
    updateSidebarState: () => void;
    destroy: () => void;
    // Event listener references for cleanup
    keydownHandler: ((e: KeyboardEvent) => void) | null;
    resizeHandler: (() => void) | null;
    touchStartHandler: ((e: TouchEvent) => void) | null;
    touchEndHandler: ((e: TouchEvent) => void) | null;
    mainClickHandler: ((e: MouseEvent) => void) | null;
    mainElement: HTMLElement | null;  // Store reference to prevent memory leak
}

const SWIPE_THRESHOLD = 100;
const MOBILE_BREAKPOINT = 991.98;

// Create global sidebar store (will be initialized when Alpine starts)

export function registerSidebar(): void {
    // Sidebar store is initialized in alpine-init.ts
    // Note: $el and $watch are injected by Alpine.js at runtime
    Alpine.data('sidebar', () => {
        return {
            open: false,
            touchStartX: 0,
            touchEndX: 0,
            keydownHandler: null,
            resizeHandler: null,
            touchStartHandler: null,
            touchEndHandler: null,
            mainClickHandler: null,
            mainElement: null,

            init(this: SidebarData) {
                // Sync initial state with store
                const store = this.$store?.sidebar;
                if (store) {
                    this.open = store.open;
                }
                
                // Watch local open property for changes
                if (this.$watch) {
                    this.$watch('open', () => {
                        this.updateSidebarState();
                    });
                }
                
                // Watch store changes and sync to local property
                // We need to poll or use a different mechanism since $watch can't watch stores directly
                // Use x-effect in template instead

                // Set initial ARIA attributes
                // Note: sidebarToggle is outside component scope (in topnav), so we use querySelector
                const sidebarToggle = document.querySelector('.js-sidebar-toggle') as HTMLElement;

                if (sidebarToggle) {
                    sidebarToggle.setAttribute('aria-expanded', 'false');
                    sidebarToggle.setAttribute('aria-label', 'Open navigation menu');
                    sidebarToggle.setAttribute('aria-controls', 'sidebar');
                }

                // Set up global keyboard shortcuts - store handler reference
                this.keydownHandler = (e: KeyboardEvent) => this.handleKeydown(e);
                document.addEventListener('keydown', this.keydownHandler);

                // Set up resize handler - store handler reference
                this.resizeHandler = () => this.handleResize();
                window.addEventListener('resize', this.resizeHandler);

                // Set up touch handlers for swipe gestures - store handler references
                this.touchStartHandler = (e: TouchEvent) => this.handleTouchStart(e);
                this.touchEndHandler = (e: TouchEvent) => this.handleTouchEnd(e);
                document.addEventListener('touchstart', this.touchStartHandler, { passive: true });
                document.addEventListener('touchend', this.touchEndHandler, { passive: true });

                // Close sidebar when clicking on main content (mobile only)
                // Store element reference to avoid memory leak on DOM changes
                const main = document.querySelector('.main') as HTMLElement | null;
                if (main) {
                    this.mainElement = main;  // Store reference for cleanup
                    this.mainClickHandler = (e: MouseEvent) => {
                        if (this.open && this.mainElement?.classList.contains('sidebar-mobile-show')) {
                            const target = e.target as HTMLElement;
                            if (target === this.mainElement) {
                                this.close();
                            }
                        }
                    };
                    this.mainElement.addEventListener('click', this.mainClickHandler);
                }
            },

            toggle(this: SidebarData): void {
                const store = this.$store?.sidebar;
                if (store) {
                    store.toggle();
                    this.open = store.open;
                } else {
                    this.open = !this.open;
                }
                this.updateSidebarState();
            },

            close(this: SidebarData): void {
                if (this.open) {
                    const store = this.$store?.sidebar;
                    if (store) {
                        store.close();
                        // x-effect will sync the store value to this.open
                    } else {
                        // Fallback if store not available
                        this.open = false;
                    }
                    // updateSidebarState will be called by $watch('open')
                    
                    // Return focus to toggle button (outside component scope, use querySelector)
                    if (this.$nextTick) {
                        this.$nextTick(() => {
                            const sidebarToggle = document.querySelector('.js-sidebar-toggle') as HTMLElement;
                            if (sidebarToggle) {
                                sidebarToggle.focus();
                            }
                        });
                    }
                }
            },


            updateSidebarState(this: SidebarData): void {
                // Note: main and sidebarToggle are outside component scope, so we use querySelector
                const main = document.querySelector('.main');
                const sidebarToggle = document.querySelector('.js-sidebar-toggle') as HTMLElement;

                if (!main) {
                    console.warn('Sidebar: .main element not found');
                    return;
                }

                if (!sidebarToggle) {
                    console.warn('Sidebar: .js-sidebar-toggle element not found');
                    return;
                }

                if (this.open) {
                    this.$el.classList.add('sidebar-mobile-show');
                    main.classList.add('sidebar-mobile-show');
                    sidebarToggle.setAttribute('aria-expanded', 'true');
                    sidebarToggle.setAttribute('aria-label', 'Close navigation menu');

                    // Focus first link when opening - use $el since sidebar is the component root
                    if (this.$nextTick) {
                        this.$nextTick(() => {
                            const firstLink = this.$el.querySelector('.sidebar-link') as HTMLElement;
                            if (firstLink) {
                                firstLink.focus();
                            }
                        });
                    }
                    this.$el.classList.remove('sidebar-mobile-show');
                    main.classList.remove('sidebar-mobile-show');
                    sidebarToggle.setAttribute('aria-expanded', 'false');
                    sidebarToggle.setAttribute('aria-label', 'Open navigation menu');
                }
            },

            handleSwipe(this: SidebarData): void {
                const swipeDistance = this.touchEndX - this.touchStartX;

                // Swipe from left edge to open
                if (this.touchStartX < 50 && swipeDistance > SWIPE_THRESHOLD && !this.open) {
                    this.toggle();
                }

                // Swipe right to close
                if (swipeDistance < -SWIPE_THRESHOLD && this.open) {
                    this.close();
                }
            },

            handleKeydown(this: SidebarData, event: KeyboardEvent): void {
                // Escape key closes sidebar
                if (event.key === 'Escape' && this.open) {
                    this.close();
                    return;
                }

                // Ctrl/Cmd + M toggles sidebar
                if ((event.ctrlKey || event.metaKey) && event.key === 'm') {
                    event.preventDefault();
                    this.toggle();
                }
            },

            handleResize(this: SidebarData): void {
                // Auto-close on desktop
                if (window.innerWidth > MOBILE_BREAKPOINT && this.open) {
                    this.close();
                }
            },

            handleTouchStart(this: SidebarData, event: TouchEvent): void {
                this.touchStartX = event.changedTouches[0].screenX;
            },

            handleTouchEnd(this: SidebarData, event: TouchEvent): void {
                this.touchEndX = event.changedTouches[0].screenX;
                this.handleSwipe();
            },

            destroy(this: SidebarData): void {
                // Remove all event listeners
                if (this.keydownHandler) {
                    document.removeEventListener('keydown', this.keydownHandler);
                    this.keydownHandler = null;
                }

                if (this.resizeHandler) {
                    window.removeEventListener('resize', this.resizeHandler);
                    this.resizeHandler = null;
                }

                if (this.touchStartHandler) {
                    document.removeEventListener('touchstart', this.touchStartHandler);
                    this.touchStartHandler = null;
                }

                if (this.touchEndHandler) {
                    document.removeEventListener('touchend', this.touchEndHandler);
                    this.touchEndHandler = null;
                }

                if (this.mainClickHandler && this.mainElement) {
                    this.mainElement.removeEventListener('click', this.mainClickHandler);
                    this.mainClickHandler = null;
                    this.mainElement = null;  // Clear element reference
                }

                // Reset state
                this.open = false;
                this.touchStartX = 0;
                this.touchEndX = 0;
            }
        };
    });
}
