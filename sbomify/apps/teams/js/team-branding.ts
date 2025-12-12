import Alpine from 'alpinejs';
import { showSuccess, showError } from '../../core/js/alerts';

interface BrandingInfo {
    icon: File | null;
    logo: File | null;
    icon_url: string;
    logo_url: string;
    prefer_logo_over_icon: boolean;
    branding_enabled?: boolean;
    brand_color: string;
    accent_color: string;
    icon_pending_deletion?: boolean;
    logo_pending_deletion?: boolean;
}

type FileFields = 'icon' | 'logo';

interface CustomDomainConfig {
    teamKey: string;
    initialDomain: string;
    isValidated: boolean;
    lastCheckedAt: string;
    hasAccess: boolean;
}

export function registerCustomDomain() {
    Alpine.data('customDomain', (config: CustomDomainConfig) => ({
        teamKey: config.teamKey,
        currentDomain: config.initialDomain || '',
        localDomain: config.initialDomain || '',
        validated: config.isValidated,
        lastChecked: config.lastCheckedAt || null,
        hasAccess: config.hasAccess,
        isLoading: false,
        error: '',

        hasUnsavedChanges() {
            return this.localDomain !== this.currentDomain;
        },

        canSave() {
            return this.localDomain.trim() !== '' && this.hasUnsavedChanges();
        },

        cancelChanges() {
            this.localDomain = this.currentDomain;
            this.error = '';
        },

        formatLastChecked() {
            if (!this.lastChecked) return 'Never';
            try {
                const date = new Date(this.lastChecked);
                return date.toLocaleString();
            } catch {
                return 'Unknown';
            }
        },

        async saveDomain() {
            const domain = this.localDomain.trim();
            if (!domain) {
                this.error = 'Please enter a domain';
                return;
            }

            this.isLoading = true;
            this.error = '';

            try {
                const response = await fetch(`/api/v1/workspaces/${this.teamKey}/domain`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ domain }),
                });

                const data = await response.json();

                if (!response.ok) {
                    this.error = data.detail || 'Failed to save domain';
                    showError(this.error);
                    return;
                }

                // Update state with response
                this.currentDomain = data.domain;
                this.localDomain = data.domain;
                this.validated = data.validated;
                this.error = '';

                showSuccess('Custom domain saved successfully');
            } catch {
                this.error = 'Network error. Please try again.';
                showError(this.error);
            } finally {
                this.isLoading = false;
            }
        },

        async removeDomain() {
            if (!confirm('Are you sure you want to remove the custom domain?')) {
                return;
            }

            this.isLoading = true;
            this.error = '';

            try {
                const response = await fetch(`/api/v1/workspaces/${this.teamKey}/domain`, {
                    method: 'DELETE',
                });

                if (!response.ok) {
                    const data = await response.json();
                    this.error = data.detail || 'Failed to remove domain';
                    showError(this.error);
                    return;
                }

                // Clear state
                this.currentDomain = '';
                this.localDomain = '';
                this.validated = false;
                this.lastChecked = null;
                this.error = '';

                showSuccess('Custom domain removed successfully');
            } catch {
                this.error = 'Network error. Please try again.';
                showError(this.error);
            } finally {
                this.isLoading = false;
            }
        },
    }));
}

export function registerTeamBranding() {
    Alpine.data('teamBranding', (brandingInfoJson: string) => {
        const defaultColors = {
            brand_color: '#4f46e5',
            accent_color: '#7c8b9d',
        };

        return {
            initialBrandingInfo: JSON.parse(brandingInfoJson) as BrandingInfo,
            normalizedInitialBranding: {} as BrandingInfo,
            localBrandingInfo: JSON.parse(brandingInfoJson) as BrandingInfo,
            uiColors: {
                brand_color: '',
                accent_color: '',
            },

            init() {
                // Normalize once and keep an immutable baseline for change detection.
                this.normalizedInitialBranding = {
                    ...this.initialBrandingInfo,
                    branding_enabled: this.initialBrandingInfo.branding_enabled ?? false,
                };
                // Clone the normalized initial into local state.
                this.localBrandingInfo = { ...this.normalizedInitialBranding };

                // Seed UI state with saved values or defaults so the native color picker works reliably.
                this.uiColors.brand_color = this.localBrandingInfo.brand_color || defaultColors.brand_color;
                this.uiColors.accent_color = this.localBrandingInfo.accent_color || defaultColors.accent_color;
            },

            hasUnsavedChanges() {
                return JSON.stringify(this.localBrandingInfo) !== JSON.stringify(this.normalizedInitialBranding);
            },

            handleFileFromComponent(field: FileFields, file: File) {
                const dt = new DataTransfer();
                dt.items.add(file);
                const input = document.querySelector<HTMLInputElement>(
                    `#team-branding-form [name="${field}"]`
                );
                if (input) input.files = dt.files;

                this.localBrandingInfo[field] = file;
                this.localBrandingInfo[`${field}_pending_deletion`] = false;
            },

            removeFile(field: FileFields) {
                const input = document.querySelector<HTMLInputElement>(
                    `#team-branding-form [name="${field}"]`
                );
                if (input) input.value = '';
                this.localBrandingInfo[field] = null;
            },

            handleExistingFileRemoval(field: FileFields) {
                this.localBrandingInfo[`${field}_url`] = '';
                this.localBrandingInfo[`${field}_pending_deletion`] = true;
            },

            updateColor(field: 'brand_color' | 'accent_color', value: string) {
                this.uiColors[field] = value;
                this.localBrandingInfo[field] = value;
            },

            setDefaultColors() {
                this.updateColor('brand_color', defaultColors.brand_color);
                this.updateColor('accent_color', defaultColors.accent_color);
            },

            displayColor(field: 'brand_color' | 'accent_color') {
                const value = this.localBrandingInfo[field];
                const hasInitial = !!this.initialBrandingInfo[field];
                const isFallbackDefault = !hasInitial && value === defaultColors[field];

                if (!value || isFallbackDefault) {
                    return 'Not set';
                }

                return value;
            },
        };
    });
}
