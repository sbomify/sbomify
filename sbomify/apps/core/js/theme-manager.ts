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

function applyTheme(theme: Theme): void {
  const effectiveTheme = theme === 'system' ? getSystemTheme() : theme;

  // Remove both classes first
  document.documentElement.classList.remove('light', 'dark');

  // Apply the effective theme
  document.documentElement.classList.add(effectiveTheme);

  // Update color-scheme meta
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) {
    meta.setAttribute('content', effectiveTheme);
  }
}

function setTheme(theme: Theme): void {
  localStorage.setItem(STORAGE_KEY, theme);
  applyTheme(theme);

  // Dispatch custom event for other components to react
  window.dispatchEvent(new CustomEvent('theme-changed', { detail: { theme } }));
}

function initThemeManager(): void {
  // Apply stored theme immediately
  const storedTheme = getStoredTheme();
  applyTheme(storedTheme);

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
