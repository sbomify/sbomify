/**
 * Layout Interactions
 * 
 * Global Setup File
 * 
 * This file sets up application-wide layout initialization that persists for the
 * lifetime of the application. Event listeners are intentionally global and
 * do not require cleanup.
 * 
 * Global setup files vs Component-scoped:
 * - Global: Application-wide, persists for app lifetime, no cleanup needed
 * - Component-scoped: Per-component, requires destroy() cleanup
 * 
 * NOTE: Most functionality has been migrated to Alpine.js components:
 * - Sidebar: sbomify/apps/core/js/components/sidebar.ts
 * - Tooltips: sbomify/apps/core/js/components/tooltip-manager.ts
 * - Dropdowns: sbomify/apps/core/js/components/dropdown-manager.ts
 * - Modal Focus: sbomify/apps/core/js/components/modal-focus-manager.ts
 * 
 * This file is kept for:
 * - Bootstrap global setup
 * - Sidebar keyboard navigation (can be enhanced in sidebar component)
 * - Backward compatibility
 */

// Bootstrap module removed - using Alpine.js instead

declare global {
  interface Window {
    bootstrap?: unknown; // Bootstrap JS removed, kept for backward compatibility
    __sbomifyLayoutInitialized?: boolean;
  }
}

const win = window as Window & { __sbomifyLayoutInitialized?: boolean };

// Workspace selector functionality moved to workspaceSwitcher Alpine component
// See: sbomify/apps/core/js/components/workspace-switcher.ts
function initializeWorkspaceSelector() {
  // Workspace switching is now handled by the workspaceSwitcher Alpine component
  // This function is kept for backward compatibility but does nothing
}

// Sidebar functionality has been moved to Alpine.js component
// See: sbomify/apps/core/js/components/sidebar.ts

// Fallback for sidebar toggle button (works even if Alpine isn't ready)


/**
 * Enhanced keyboard navigation for sidebar
 * This functionality can be enhanced in the sidebar Alpine component if needed
 * Currently handled by native browser keyboard navigation
 */
function initializeSidebarKeyboardNavigation() {
  // Keyboard navigation is handled by the sidebar Alpine component
  // This function is kept for backward compatibility but does nothing
  // Enhanced keyboard navigation can be added to sidebar.ts if needed
}

// Tooltip initialization moved to Alpine.js component
// See: sbomify/apps/core/js/components/tooltip-manager.ts
// Tooltips are now auto-initialized via Alpine directives and HTMX lifecycle
function initializeTooltips() {
  // Tooltips are now handled by Alpine.js tooltip-manager component
  // This function is kept for backward compatibility but does nothing
  // The tooltip-manager component handles initialization automatically
}

// Dropdown functionality moved to Alpine.js dropdown-manager component
// See: sbomify/apps/core/js/components/dropdown-manager.ts
function initializeDropdowns() {
  // Dropdowns are now handled by the dropdown-manager Alpine component
  // This function is kept for backward compatibility but does nothing
}

// Dropdown ARIA state moved to dropdown-manager component
function initializeDropdownAriaState() {
  // ARIA state is now handled by the dropdown-manager Alpine component
  // This function is kept for backward compatibility but does nothing
}

// Modal focus handlers moved to Alpine.js modal-focus-manager component
// See: sbomify/apps/core/js/components/modal-focus-manager.ts
function initializeModalFocusHandlers() {
  // Modal focus is now handled by the modal-focus-manager Alpine component
  // This function is kept for backward compatibility but does nothing
}

function startLayoutInitialization() {
  initializeWorkspaceSelector();
  // Sidebar initialization moved to Alpine.js component
  initializeSidebarKeyboardNavigation();
  initializeTooltips();
  initializeDropdowns();
  initializeDropdownAriaState();
  initializeModalFocusHandlers();
}

if (!win.__sbomifyLayoutInitialized) {
  win.__sbomifyLayoutInitialized = true;
  // Bootstrap JS removed - using Alpine.js instead
  // win.bootstrap no longer set

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startLayoutInitialization, { once: true });
  } else {
    startLayoutInitialization();
  }
}

export { };
