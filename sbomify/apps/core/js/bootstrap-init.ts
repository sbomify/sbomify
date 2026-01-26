/**
 * Bootstrap Global Initialization
 * 
 * NOTE: Bootstrap JS has been removed and replaced with Alpine.js.
 * Bootstrap CSS is still available for styling.
 * 
 * This file is kept for backward compatibility but no longer imports Bootstrap JS.
 */

declare global {
  interface Window {
    bootstrap?: unknown; // Bootstrap JS removed, kept for backward compatibility
  }
}

// Bootstrap JS removed - using Alpine.js instead
// window.bootstrap is kept as undefined for backward compatibility
// Any code checking for window.bootstrap should be updated to use Alpine.js

export { };
