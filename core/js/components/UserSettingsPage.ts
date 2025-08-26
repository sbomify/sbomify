/**
 * User Settings Page TypeScript Component
 * Handles access token management functionality
 */

// Bootstrap types are now available globally via main.ts

class UserSettingsPage {

  constructor() {
    this.initialize();
  }

  private initialize(): void {
    this.initializeTokenForm();
    this.initializeCopyToken();
  }

  private initializeTokenForm(): void {
    const form = document.getElementById('tokenGenerationForm') as HTMLFormElement;
    if (!form) return;

    // Add Bootstrap 5 form validation
    form.addEventListener('submit', (event) => {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      form.classList.add('was-validated');
    });

    // Handle clear button
    const clearButton = document.getElementById('clearTokenFormBtn') as HTMLButtonElement;
    if (clearButton) {
      clearButton.addEventListener('click', () => {
        form.reset();
        form.classList.remove('was-validated');
      });
    }
  }



  private initializeCopyToken(): void {
    // Handle both copy buttons
    const copyButton1 = document.getElementById('copyTokenBtn') as HTMLButtonElement;
    const copyButton2 = document.getElementById('copyTokenBtn2') as HTMLButtonElement;
    const tokenInput = document.getElementById('accessToken') as HTMLInputElement;

    if (tokenInput) {
      // Click to select all text
      tokenInput.addEventListener('click', () => {
        tokenInput.select();
        tokenInput.setSelectionRange(0, 99999); // For mobile
      });

      // Copy functionality for both buttons
      const copyHandler = async (button: HTMLButtonElement) => {
        try {
          await navigator.clipboard.writeText(tokenInput.value);
          this.showCopySuccess(button);
        } catch {
          this.fallbackCopyToken(tokenInput);
          this.showCopySuccess(button);
        }
      };

      if (copyButton1) {
        copyButton1.addEventListener('click', () => copyHandler(copyButton1));
      }

      if (copyButton2) {
        copyButton2.addEventListener('click', () => copyHandler(copyButton2));
      }
    }
  }

  private fallbackCopyToken(input: HTMLInputElement): void {
    input.select();
    input.setSelectionRange(0, 99999); // For mobile devices
    document.execCommand('copy');
  }

  private showCopySuccess(button: HTMLButtonElement): void {
    const originalContent = button.innerHTML;
    button.innerHTML = '<i class="fas fa-check me-2"></i>Copied!';
    button.classList.remove('btn-outline-secondary');
    button.classList.add('btn-success');

    setTimeout(() => {
      button.innerHTML = originalContent;
      button.classList.remove('btn-success');
      button.classList.add('btn-outline-secondary');
    }, 2000);
  }
}

// Make the class available globally for debugging
declare global {
  interface Window {
    UserSettingsPage: typeof UserSettingsPage;
  }
}

window.UserSettingsPage = UserSettingsPage;

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  const settingsContainer = document.querySelector('.vc-user-settings-page') as HTMLElement;

  if (settingsContainer) {
    new UserSettingsPage();
  }
});

export default UserSettingsPage;
