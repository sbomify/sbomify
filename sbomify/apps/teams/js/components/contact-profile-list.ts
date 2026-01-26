import Alpine from 'alpinejs';

interface ContactProfile {
    id: string;
    name: string;
    manufacturer?: { name: string };
    supplier?: { name: string };
    authors?: Array<{ name: string }>;
    created_at?: string;
    updated_at?: string;
    hidden?: boolean;
}

/**
 * Contact Profile List Component
 * Handles listing and filtering contact profiles
 */
export function registerContactProfileList(): void {
    Alpine.data('contactProfileList', () => {
        return {
            profiles: [] as ContactProfile[],
            filteredProfiles: [] as ContactProfile[],
            searchQuery: '',
            expandedProfiles: [] as string[],

            init() {
                this.$nextTick(() => {
                    const profilesScript = document.getElementById('profiles-data');
                    if (profilesScript) {
                        try {
                            this.profiles = JSON.parse(profilesScript.textContent || '[]');
                            this.filteredProfiles = this.profiles.map(p => ({ ...p, hidden: false }));
                        } catch (e) {
                            console.error('Error parsing profiles data:', e);
                            this.profiles = [];
                        }
                    }

                    this.$nextTick(() => {
                        this.initTooltips();
                    });
                });
            },

            initTooltips() {
                // Alpine tooltips auto-initialize from data-bs-toggle="tooltip" or title attributes
                // No manual initialization needed
            },

            togglePreview(profileId: string) {
                if (this.expandedProfiles.includes(profileId)) {
                    this.expandedProfiles = this.expandedProfiles.filter(id => id !== profileId);
                } else {
                    this.expandedProfiles.push(profileId);
                }
            },

            filterProfiles() {
                const query = this.searchQuery.toLowerCase().trim();

                this.filteredProfiles = this.profiles.map(profile => {
                    let matches = true;

                    if (query) {
                        const nameMatch = profile.name?.toLowerCase().includes(query);
                        const mfgMatch = profile.manufacturer?.name?.toLowerCase().includes(query);
                        const supMatch = profile.supplier?.name?.toLowerCase().includes(query);
                        const authorMatch = (profile.authors || []).some(a =>
                            a.name?.toLowerCase().includes(query)
                        );
                        matches = nameMatch || mfgMatch || supMatch || authorMatch;
                    }

                    return { ...profile, hidden: !matches };
                });
            },

            formatDate(dateStr: string | undefined): string {
                if (!dateStr) return '';
                const date = new Date(dateStr);
                return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
            }
        };
    });
}
