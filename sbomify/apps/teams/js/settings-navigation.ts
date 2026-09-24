import Alpine from 'alpinejs';

/** Resolve older fragment links through the same permitted links shown in the nav. */
export function registerSettingsNavigation() {
    Alpine.data('settingsNavigation', () => ({
        init() {
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
    }));
}
