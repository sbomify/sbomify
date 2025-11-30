import Alpine from 'alpinejs';

interface BrandingInfo {
    icon: File | null;
    logo: File | null;
    icon_url: string;
    logo_url: string;
    prefer_logo_over_icon: boolean;
    brand_color: string;
    accent_color: string;
    icon_pending_deletion?: boolean;
    logo_pending_deletion?: boolean;
}

type FileFields = 'icon' | 'logo';

export function registerTeamBranding() {
    Alpine.data('teamBranding', (brandingInfoJson: string) => {
        return {
            initialBrandingInfo: JSON.parse(brandingInfoJson) as BrandingInfo,
            localBrandingInfo: JSON.parse(brandingInfoJson) as BrandingInfo,

            hasUnsavedChanges() {
                return JSON.stringify(this.localBrandingInfo) !== JSON.stringify(this.initialBrandingInfo);
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
            }
        };
    });
}
