/**
 * Alpine.js Component Registry
 * 
 * Centralized registration of all Alpine.data components.
 * initializeAlpine() registers this set before any entry point starts the DOM.
 */
import Alpine from 'alpinejs';

// ============================================
// COMPONENT IMPORTS - Core
// ============================================
import { navbarSearch } from './navbar-search';
import { scrollableTabs } from './components/scrollable-tabs';
import { repositorySetup } from './components/repository-setup';
import { registerCopyableValue } from './components/copyable-value';
import { registerVisibilitySelector } from './components/visibility-selector';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerAccessTokensList } from './components/access-tokens-list';
import { registerDeleteModal } from './components/delete-modal';
import { registerCopyToken } from './components/copy-token';
import { registerSiteNotifications } from './components/site-notifications';
import { registerEditableSingleField } from './components/editable-single-field';
import { registerProductIdentifiers } from './components/product-identifiers';
import { registerReleaseEditor } from './components/release-editor';
import { registerReleaseArtifacts } from './components/release-artifacts';
import { registerProductIdentifiersBarcodes } from './components/product-identifiers-barcodes';
import { registerComponentMetaInfoEditor } from './component-meta-info-editor';
import { registerComponentMetaInfo } from './component-meta-info';
import { registerTeamGeneral } from '../../teams/js/team-general';
import { registerSettingsNavigation } from '../../teams/js/settings-navigation';
import { registerTeamBranding, registerCustomDomain } from '../../teams/js/team-branding';
import { registerFileDragAndDrop } from './components/file-drag-and-drop';
import { registerAccountDangerZone } from './components/account-danger-zone';
import { registerDatePicker } from './components/date-picker';
import { advisoryProductPicker } from './components/advisory-product-picker';
import { actionsMenu } from './components/actions-menu';
import { publicSharing } from './components/public-sharing';
import { uploadDialog } from './components/upload-dialog';
import { catalogImport } from '../../controls/js/catalog-import';

// ============================================
// COMPONENT IMPORTS - SBOM Module
// ============================================
import { registerSbomUpload } from '../../sboms/js/sbom-upload';
import { registerSbomsTable } from '../../sboms/js/sboms-table';
import { registerLicensesEditor } from '../../sboms/js/licenses-editor';
import { registerContactsEditor } from '../../sboms/js/contacts-editor';
import { registerSupplierEditor } from '../../sboms/js/supplier-editor';

// ============================================
// COMPONENT IMPORTS - Other Modules
// ============================================
import { registerDocumentUpload } from '../../documents/js/document-upload';
import { registerPlanSelection } from '../../billing/js/plan-selection';
import { vulnerabilityTrends } from '../../vulnerability_scanning/js/vulnerability-chart';

// ============================================
// COMPONENT IMPORTS - Compliance Module
// ============================================
import { registerCraDocSignature } from '../../compliance/js/cra-doc-signature';
import { registerCraScopeScreening } from '../../compliance/js/cra-scope-screening';
import { registerCraStep1 } from '../../compliance/js/cra-step-1';
import { registerCraStep2 } from '../../compliance/js/cra-step-2';
import { registerCraStep3 } from '../../compliance/js/cra-step-3';
import { registerCraStep4 } from '../../compliance/js/cra-step-4';
import { registerCraStep5 } from '../../compliance/js/cra-step-5';
import { registerCiCdToken } from '../../sboms/js/ci-cd-token';

// Track registered components to prevent double-registration
const registeredComponents = new Set<string>();

/**
 * Safely register an Alpine.data component.
 * Prevents duplicate registration.
 */
export function registerAlpineComponent(
    name: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: (...args: any[]) => object
): void {
    if (registeredComponents.has(name)) {
        return;
    }
    Alpine.data(name, component);
    registeredComponents.add(name);
}

/**
 * Check if a component is already registered
 */
export function isComponentRegistered(name: string): boolean {
    return registeredComponents.has(name);
}

/**
 * Get list of all registered component names
 */
export function getRegisteredComponents(): string[] {
    return Array.from(registeredComponents);
}

// ============================================
// COMMON REUSABLE ALPINE COMPONENTS
// ============================================

/**
 * Danger Zone Component
 * Used across multiple templates for delete confirmation patterns.
 */
export function dangerZone() {
    return {
        showDeleteModal: false,
        isExpanded: false,
        confirmText: '',

        get canConfirm(): boolean {
            return this.confirmText.toLowerCase() === 'delete';
        },

        toggle(): void {
            this.isExpanded = !this.isExpanded;
        },

        openDelete(): void {
            this.showDeleteModal = true;
        },

        closeDelete(): void {
            this.showDeleteModal = false;
            this.confirmText = '';
        }
    };
}

/**
 * Modal State Component
 */
export function modalState() {
    return {
        isOpen: false,
        open(): void { this.isOpen = true; },
        close(): void { this.isOpen = false; },
        toggle(): void { this.isOpen = !this.isOpen; }
    };
}

/**
 * Collapsible Section Component
 */
export function collapsible(defaultExpanded = false) {
    return {
        isExpanded: defaultExpanded,
        toggle(): void { this.isExpanded = !this.isExpanded; },
        expand(): void { this.isExpanded = true; },
        collapse(): void { this.isExpanded = false; }
    };
}

/**
 * Form State Component
 */
export function formState() {
    return {
        editing: false,
        submitting: false,
        error: null as string | null,

        startEdit(): void { this.editing = true; },
        cancelEdit(): void { this.editing = false; this.error = null; },
        submit(): void { this.submitting = true; this.error = null; },
        submitComplete(success: boolean, errorMessage?: string): void {
            this.submitting = false;
            if (success) {
                this.editing = false;
            } else {
                this.error = errorMessage || 'An error occurred';
            }
        }
    };
}

// ============================================
// REGISTRATION FUNCTIONS
// ============================================

/**
 * Register common inline components (dangerZone, modalState, etc.)
 */
export function registerCommonComponents(): void {
    registerAlpineComponent('navbarSearch', navbarSearch);
    registerAlpineComponent('scrollableTabs', scrollableTabs);
    registerAlpineComponent('vulnerabilityTrends', vulnerabilityTrends);
    registerAlpineComponent('dangerZone', dangerZone);
    registerAlpineComponent('modalState', modalState);
    registerAlpineComponent('collapsible', collapsible);
    registerAlpineComponent('formState', formState);
    registerAlpineComponent('advisoryProductPicker', advisoryProductPicker);
    registerAlpineComponent('actionsMenu', actionsMenu);
    registerAlpineComponent('publicSharing', publicSharing);
    registerAlpineComponent('uploadDialog', uploadDialog);
    registerAlpineComponent('catalogImport', catalogImport);
}

/**
 * Register all Alpine.js components from across the application.
 * Called once by initializeAlpine(), including when a page bundle starts first.
 */
export function registerAllComponents(): void {
    Alpine.data('repositorySetup', repositorySetup);
    // Common inline components
    registerCiCdToken();
    registerCommonComponents();

    // Core components
    registerCopyableValue();
    registerVisibilitySelector();
    registerWorkspaceSwitcher();
    registerAccessTokensList();
    registerDeleteModal();
    // confirmModal is registered in alpine-init.ts (base template dependency)
    registerCopyToken();
    registerSiteNotifications();
    registerEditableSingleField();
    registerProductIdentifiers();
    registerReleaseEditor();
    registerReleaseArtifacts();
    registerProductIdentifiersBarcodes();
    registerComponentMetaInfoEditor();
    registerComponentMetaInfo();
    registerAccountDangerZone();
    registerTeamGeneral();
    registerSettingsNavigation();
    registerTeamBranding();
    registerCustomDomain();
    registerFileDragAndDrop();
    registerDatePicker();

    // SBOM module components
    registerSbomUpload();
    registerSbomsTable();
    registerLicensesEditor();
    registerContactsEditor();
    registerSupplierEditor();

    // Other modules
    registerDocumentUpload();
    registerPlanSelection();

    // Compliance module
    registerCraScopeScreening();
    registerCraStep1();
    registerCraStep2();
    registerCraStep3();
    registerCraStep4();
    registerCraStep5();
    registerCraDocSignature();
}

export default {
    registerAlpineComponent,
    isComponentRegistered,
    getRegisteredComponents,
    registerCommonComponents,
    registerAllComponents,
    // Common components
    dangerZone,
    modalState,
    collapsible,
    formState
};
