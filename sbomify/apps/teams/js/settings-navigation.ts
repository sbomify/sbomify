import Alpine from 'alpinejs';

/** Resolve older fragment links through the same permitted links shown in the nav. */
export function registerSettingsNavigation() {
    Alpine.data('settingsNavigation', () => ({
        observer: null as ResizeObserver | null,
        init() {
            const navigation = this.$el.querySelector<HTMLElement>('[role="navigation"]');
            if (navigation) {
                this.observer = new ResizeObserver(() => {
                    const active = navigation.querySelector<HTMLElement>('[aria-current="page"]');
                    if (!active) return;
                    const navRect = navigation.getBoundingClientRect();
                    const activeRect = active.getBoundingClientRect();
                    // Reveal the selected tab without scrolling the page vertically.
                    if (activeRect.left < navRect.left || activeRect.right > navRect.right) {
                        navigation.scrollLeft += activeRect.left - navRect.left -
                            (navigation.clientWidth - activeRect.width) / 2;
                    }
                });
                this.observer.observe(navigation);
            }
            const key = window.location.hash.slice(1);
            if (!key) return;
            const alias = key === 'parties' ? 'contact-profiles' : key;
            const links = this.$el.querySelectorAll<HTMLAnchorElement>('a[data-settings-tab]');
            const target = Array.from(links).find(link => link.dataset.settingsTab === alias);
            if (!target) return;
            if (target.pathname === window.location.pathname) {
                window.history.replaceState(window.history.state, '', target.href);
            } else {
                window.location.replace(target.href);
            }
        },
        destroy() {
            this.observer?.disconnect();
        },
    }));
}
