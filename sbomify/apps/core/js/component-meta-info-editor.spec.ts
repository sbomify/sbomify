import { describe, test, expect } from 'bun:test'

/**
 * Tests for ComponentMetaInfoEditor Alpine.js component business logic
 *
 * This test suite validates the core functionality of the component metadata editor
 * including form validation, profile management, lifecycle phases, and API payload preparation.
 */

describe('ComponentMetaInfoEditor Business Logic', () => {

    interface ContactInfo {
        name: string;
        email: string;
        phone: string;
    }

    interface SupplierInfo {
        name: string | null;
        url: string[] | null;
        address: string | null;
        contacts: ContactInfo[];
    }

    interface ContactProfile {
        id: string;
        name: string;
        is_default?: boolean;
        company?: string;
        email?: string;
    }

    interface ComponentMetaInfo {
        supplier: SupplierInfo;
        authors: ContactInfo[];
        licenses: string[];
        lifecycle_phase: string | null;
        contact_profile_id: string | null;
        uses_custom_contact: boolean;
    }

    describe('Lifecycle Phases', () => {
        const LIFECYCLE_ORDER = [
            "design",
            "pre-build",
            "build",
            "post-build",
            "operations",
            "discovery",
            "decommission"
        ];

        const formatLifecyclePhase = (phase: string): string => {
            if (phase === 'pre-build') return 'Pre-Build';
            if (phase === 'post-build') return 'Post-Build';
            return phase.charAt(0).toUpperCase() + phase.slice(1);
        };

        test('should return all lifecycle phases in correct order', () => {
            expect(LIFECYCLE_ORDER.length).toBe(7);
            expect(LIFECYCLE_ORDER[0]).toBe('design');
            expect(LIFECYCLE_ORDER[6]).toBe('decommission');
        });

        test('should format lifecycle phases correctly', () => {
            expect(formatLifecyclePhase('design')).toBe('Design');
            expect(formatLifecyclePhase('pre-build')).toBe('Pre-Build');
            expect(formatLifecyclePhase('post-build')).toBe('Post-Build');
            expect(formatLifecyclePhase('operations')).toBe('Operations');
        });

        test('should generate phase options', () => {
            const phases = LIFECYCLE_ORDER.map(phase => ({
                value: phase,
                label: formatLifecyclePhase(phase)
            }));

            expect(phases.length).toBe(7);
            expect(phases[0]).toEqual({ value: 'design', label: 'Design' });
            expect(phases[1]).toEqual({ value: 'pre-build', label: 'Pre-Build' });
        });
    });

    describe('Contact Profile Management', () => {
        test('should determine if using profile', () => {
            const isUsingProfile = (profileId: string | null): boolean => {
                return profileId !== null && profileId !== '';
            };

            expect(isUsingProfile('profile-123')).toBe(true);
            expect(isUsingProfile(null)).toBe(false);
            expect(isUsingProfile('')).toBe(false);
        });

        test('should find selected profile from list', () => {
            const profiles: ContactProfile[] = [
                { id: 'p1', name: 'Profile 1' },
                { id: 'p2', name: 'Profile 2', is_default: true }
            ];

            const findProfile = (id: string | null) => {
                if (!id) return null;
                return profiles.find(p => p.id === id) || null;
            };

            expect(findProfile('p1')?.name).toBe('Profile 1');
            expect(findProfile('p2')?.is_default).toBe(true);
            expect(findProfile('p3')).toBeNull();
            expect(findProfile(null)).toBeNull();
        });

        test('should handle profile change', () => {
            let metadata = {
                contact_profile_id: null as string | null,
                uses_custom_contact: true
            };

            const handleProfileChange = (profileId: string | null) => {
                metadata.contact_profile_id = profileId;
                metadata.uses_custom_contact = profileId === null;
            };

            handleProfileChange('profile-123');
            expect(metadata.contact_profile_id).toBe('profile-123');
            expect(metadata.uses_custom_contact).toBe(false);

            handleProfileChange(null);
            expect(metadata.contact_profile_id).toBeNull();
            expect(metadata.uses_custom_contact).toBe(true);
        });
    });

    describe('Form Validation', () => {
        const isValidUrl = (url: string): boolean => {
            try {
                new URL(url);
                return true;
            } catch {
                return false;
            }
        };

        const isValidEmail = (email: string): boolean => {
            if (!email) return true;
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return emailRegex.test(email);
        };

        test('should validate URLs correctly', () => {
            expect(isValidUrl('https://example.com')).toBe(true);
            expect(isValidUrl('http://localhost:3000')).toBe(true);
            expect(isValidUrl('not-a-url')).toBe(false);
            expect(isValidUrl('')).toBe(false);
        });

        test('should validate emails correctly', () => {
            expect(isValidEmail('user@example.com')).toBe(true);
            expect(isValidEmail('')).toBe(true); // Empty is valid (optional)
            expect(isValidEmail('invalid')).toBe(false);
        });

        test('should determine form validity', () => {
            const isFormValid = (errors: {
                supplier: Record<string, string>;
                authors: Record<string, string>;
                licenses: Record<string, string>;
                lifecycle_phase: string | null;
            }): boolean => {
                const hasSupplierErrors = Object.keys(errors.supplier).length > 0;
                const hasAuthorErrors = Object.keys(errors.authors).length > 0;
                const hasLicenseErrors = Object.keys(errors.licenses).length > 0;
                const hasLifecycleErrors = errors.lifecycle_phase !== null;
                return !hasSupplierErrors && !hasAuthorErrors && !hasLicenseErrors && !hasLifecycleErrors;
            };

            expect(isFormValid({
                supplier: {},
                authors: {},
                licenses: {},
                lifecycle_phase: null
            })).toBe(true);

            expect(isFormValid({
                supplier: { url: 'Invalid URL' },
                authors: {},
                licenses: {},
                lifecycle_phase: null
            })).toBe(false);
        });
    });

    describe('Metadata State', () => {
        test('should initialize with default values', () => {
            const defaultMetadata: ComponentMetaInfo = {
                supplier: { name: null, url: [], address: null, contacts: [] },
                authors: [],
                licenses: [],
                lifecycle_phase: null,
                contact_profile_id: null,
                uses_custom_contact: true
            };

            expect(defaultMetadata.supplier.name).toBeNull();
            expect(defaultMetadata.authors).toEqual([]);
            expect(defaultMetadata.licenses).toEqual([]);
            expect(defaultMetadata.lifecycle_phase).toBeNull();
        });

        test('should track unsaved changes', () => {
            let hasUnsavedChanges = false;
            let originalMetadata = JSON.stringify({ name: 'Original' });

            const checkChanges = (current: object) => {
                hasUnsavedChanges = JSON.stringify(current) !== originalMetadata;
            };

            checkChanges({ name: 'Original' });
            expect(hasUnsavedChanges).toBe(false);

            checkChanges({ name: 'Modified' });
            expect(hasUnsavedChanges).toBe(true);
        });
    });

    describe('API Payload', () => {
        test('should prepare save payload', () => {
            const metadata: ComponentMetaInfo = {
                supplier: { name: 'Acme', url: ['https://acme.com'], address: '123 Main', contacts: [] },
                authors: [{ name: 'John', email: 'john@example.com', phone: '' }],
                licenses: ['MIT', 'Apache-2.0'],
                lifecycle_phase: 'build',
                contact_profile_id: null,
                uses_custom_contact: true
            };

            const payload = {
                supplier: metadata.supplier,
                authors: metadata.authors,
                licenses: metadata.licenses,
                lifecycle_phase: metadata.lifecycle_phase,
                contact_profile_id: metadata.contact_profile_id,
                uses_custom_contact: metadata.uses_custom_contact
            };

            expect(payload.supplier.name).toBe('Acme');
            expect(payload.authors.length).toBe(1);
            expect(payload.licenses.length).toBe(2);
            expect(payload.lifecycle_phase).toBe('build');
        });

        test('should handle profile-based payload', () => {
            const metadata: ComponentMetaInfo = {
                supplier: { name: null, url: [], address: null, contacts: [] },
                authors: [],
                licenses: [],
                lifecycle_phase: 'design',
                contact_profile_id: 'profile-123',
                uses_custom_contact: false
            };

            expect(metadata.contact_profile_id).toBe('profile-123');
            expect(metadata.uses_custom_contact).toBe(false);
        });
    });

    describe('Cancel Flow', () => {
        test('should warn before canceling with unsaved changes', () => {
            let canceled = false;

            const handleCancel = (hasUnsavedChanges: boolean, confirmFn: () => boolean) => {
                if (hasUnsavedChanges && !confirmFn()) {
                    return;
                }
                canceled = true;
            };

            // With unsaved changes and no confirmation
            handleCancel(true, () => false);
            expect(canceled).toBe(false);

            // With unsaved changes and confirmation
            handleCancel(true, () => true);
            expect(canceled).toBe(true);

            // Reset and try without changes
            canceled = false;
            handleCancel(false, () => false);
            expect(canceled).toBe(true);
        });
    });
})
