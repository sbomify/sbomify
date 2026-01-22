/**
 * Alpine.js Component Registry
 * 
 * Centralized registration of all Alpine.data components.
 * Import registerAllComponents() to register all Alpine components in one place.
 */
import Alpine from 'alpinejs';

// ============================================
// COMPONENT IMPORTS - Core
// ============================================
import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { registerComponentVisibilitySelector } from './components/component-visibility-selector';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerAccessTokensList } from './components/access-tokens-list';
import { registerDeleteModal } from './components/delete-modal';
import { registerReleaseList } from './components/release-list';
import { registerStandardCard } from './components/standard-card';
import { registerCopyToken } from './components/copy-token';
import { registerSiteNotifications } from './components/site-notifications';
import { registerPlanCard } from './components/plan-card';
import { registerEditableSingleField } from './components/editable-single-field';
import { registerProductIdentifiers } from './components/product-identifiers';
import { registerItemsListTable } from './components/items-list-table';
import { registerItemAssignmentManager } from './components/item-assignment-manager';
import { registerProductReleases } from './components/product-releases';
import { registerReleaseArtifacts } from './components/release-artifacts';
import { registerProductIdentifiersBarcodes } from './components/product-identifiers-barcodes';
import { registerComponentMetaInfoEditor } from './component-meta-info-editor';
import { registerComponentMetaInfo } from './component-meta-info';

// ============================================
// COMPONENT IMPORTS - SBOM Module
// ============================================
import { registerSbomUpload } from '../../sboms/js/sbom-upload';
import { registerSbomsTable } from '../../sboms/js/sboms-table';
import { registerCiCdInfo } from '../../sboms/js/ci-cd-info';
import { registerLicensesEditor } from '../../sboms/js/licenses-editor';
import { registerContactsEditor } from '../../sboms/js/contacts-editor';
import { registerSupplierEditor } from '../../sboms/js/supplier-editor';

// ============================================
// COMPONENT IMPORTS - Other Modules
// ============================================
import { registerDocumentUpload } from '../../documents/js/document-upload';
import { registerPlanSelection } from '../../billing/js/plan-selection';
import { registerAssessmentBadge } from '../../plugins/js/assessment-badge';

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

/**
 * Chart Selector Component
 */
export function chartSelector(defaultChart = 'timeline') {
    return {
        activeChart: defaultChart,
        setChart(chartType: string): void { this.activeChart = chartType; },
        isActive(chartType: string): boolean { return this.activeChart === chartType; }
    };
}

// ============================================
// REGISTRATION FUNCTIONS
// ============================================

/**
 * Register common inline components (dangerZone, modalState, etc.)
 */
export function registerCommonComponents(): void {
    registerAlpineComponent('dangerZone', dangerZone);
    registerAlpineComponent('modalState', modalState);
    registerAlpineComponent('collapsible', collapsible);
    registerAlpineComponent('formState', formState);
    registerAlpineComponent('chartSelector', chartSelector);
}

/**
 * Register all Alpine.js components from across the application.
 * Call this once from main.ts or htmx-bundle.ts.
 */
export function registerAllComponents(): void {
    // Common inline components
    registerCommonComponents();

    // Core components
    registerCopyableValue();
    registerPublicStatusToggle();
    registerComponentVisibilitySelector();
    registerWorkspaceSwitcher();
    registerAccessTokensList();
    registerDeleteModal();
    registerStandardCard();
    registerCopyToken();
    registerSiteNotifications();
    registerPlanCard();
    registerEditableSingleField();
    registerProductIdentifiers();
    registerItemsListTable();
    registerItemAssignmentManager();
    registerProductReleases();
    registerReleaseArtifacts();
    registerProductIdentifiersBarcodes();
    registerReleaseList();
    registerComponentMetaInfoEditor();
    registerComponentMetaInfo();

    // SBOM module components
    registerSbomUpload();
    registerSbomsTable();
    registerCiCdInfo();
    registerLicensesEditor();
    registerContactsEditor();
    registerSupplierEditor();

    // Other modules
    registerDocumentUpload();
    registerPlanSelection();
    registerAssessmentBadge();
}

/**
 * Register components needed for HTMX bundle (subset, no releaseList/barcodes)
 */
export function registerHtmxBundleComponents(): void {
    // Common inline components
    registerCommonComponents();

    // Core components
    registerCopyableValue();
    registerPublicStatusToggle();
    registerComponentVisibilitySelector();
    registerWorkspaceSwitcher();
    registerAccessTokensList();
    registerDeleteModal();
    registerStandardCard();
    registerCopyToken();
    registerSiteNotifications();
    registerPlanCard();
    registerEditableSingleField();
    registerProductIdentifiers();
    registerItemsListTable();
    registerItemAssignmentManager();
    registerProductReleases();
    registerReleaseArtifacts();
    registerComponentMetaInfoEditor();
    registerComponentMetaInfo();

    // SBOM module components
    registerSbomUpload();
    registerSbomsTable();
    registerCiCdInfo();
    registerLicensesEditor();
    registerContactsEditor();
    registerSupplierEditor();

    // Other modules
    registerDocumentUpload();
    registerPlanSelection();
}

export default {
    registerAlpineComponent,
    isComponentRegistered,
    getRegisteredComponents,
    registerCommonComponents,
    registerAllComponents,
    registerHtmxBundleComponents,
    // Common components
    dangerZone,
    modalState,
    collapsible,
    formState,
    chartSelector
};
