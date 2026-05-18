/**
 * Theme Manager - Handles light/dark/system theme switching
 * Stores preference in localStorage and applies to document
 */

type Theme = 'light' | 'dark' | 'system';

interface ThemeManager {
  getTheme: () => Theme;
  setTheme: (theme: Theme) => void;
  getSystemTheme: () => 'light' | 'dark';
}

declare global {
  interface Window {
    themeManager?: ThemeManager;
  }
}

// NOTE: This key must match the inline script in base.html.j2 (for FOUC prevention)
const STORAGE_KEY = 'sbomify-theme';

function getSystemTheme(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getStoredTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }
  return 'dark'; // Default to dark theme
}

function applyTheme(theme: Theme, skipTransition = false): void {
  const effectiveTheme = theme === 'system' ? getSystemTheme() : theme;
  const oppositeTheme = effectiveTheme === 'light' ? 'dark' : 'light';

  // Skip transition during initial load to prevent FOUC
  if (skipTransition) {
    document.documentElement.classList.add('no-transitions');
  }

  // Apply the effective theme (add new before removing old to prevent flash)
  document.documentElement.classList.add(effectiveTheme);
  document.documentElement.classList.remove(oppositeTheme);

  // Update color-scheme via CSS property (keep meta as 'dark light' to declare supported schemes)
  (document.documentElement as HTMLElement).style.colorScheme = effectiveTheme;

  // Re-enable transitions after a frame
  if (skipTransition) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document.documentElement.classList.remove('no-transitions');
      });
    });
  }
}

function setTheme(theme: Theme): void {
  localStorage.setItem(STORAGE_KEY, theme);
  applyTheme(theme);

  // Dispatch custom event for other components to react
  window.dispatchEvent(new CustomEvent('theme-changed', { detail: { theme } }));
}

function initThemeManager(): void {
  // Public trust-center pages run their own theme system (see
  // ``public_base.htmx.j2``) keyed on ``data-theme="dark"|"light"`` and
  // its own ``public-theme`` localStorage key. If that attribute is
  // already on the root element when we boot, the auth-app theme
  // manager must not override it — otherwise the public page applies
  // whatever ``sbomify-theme`` the user last picked in the auth app
  // (typically light) and the trust-center renders with the wrong
  // Tailwind variable set.
  if (document.documentElement.hasAttribute('data-theme')) {
    return;
  }

  // Apply stored theme immediately, skip transitions to prevent FOUC
  const storedTheme = getStoredTheme();
  applyTheme(storedTheme, true);

  // Listen for system theme changes
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const currentTheme = getStoredTheme();
    if (currentTheme === 'system') {
      applyTheme('system');
    }
  });

  // Expose API globally for Alpine.js components
  window.themeManager = {
    getTheme: getStoredTheme,
    setTheme,
    getSystemTheme,
  };
}

export { initThemeManager, setTheme, getStoredTheme, getSystemTheme, type Theme };
