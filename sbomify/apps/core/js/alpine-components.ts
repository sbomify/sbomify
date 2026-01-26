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
import { registerSidebar } from './components/sidebar';
import { registerNotificationsModal } from './components/notifications-modal';
import { registerNavbarSearch } from './components/navbar-search';
import { registerTooltipManager } from './components/tooltip-manager';
import { registerDropdownManager } from './components/dropdown-manager';
import { registerModalFocusManager } from './components/modal-focus-manager';
import { registerAccessTokensList } from './components/access-tokens-list';

// Export mixins for use in components
export * from './components/alpine-mixins';
export * from './components/base-component';
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
import { registerComponentTypeSync } from './components/component-type-sync';
import { registerMessagesToast } from './components/messages-toast';
import { registerNotificationAutoDismiss } from './components/notification-auto-dismiss';
import { registerClipboardButton } from './components/clipboard-button';
import { registerModalFormHandler } from './components/modal-form-handler';
import { registerDjangoMessages } from './django-messages';
import { registerTurnstile } from './components/turnstile';
import { registerFileDragAndDrop } from './components/file-drag-and-drop';
import { registerScrollTo } from './components/scroll-to';
import { registerCollapsibleSection } from './components/collapsible-section';
import { registerAccordionItem } from './components/accordion-item';
import { registerChartTabSelector } from './components/chart-tab-selector';
import { registerSettingsTabs } from './components/settings-tabs';
import { registerTokenForm } from './components/token-form';
import { registerVulnerabilitySettings } from './components/vulnerability-settings';
import { registerSbomVulnerabilitiesRefresh } from './components/sbom-vulnerabilities-refresh';
import { registerAccessRequestQueue } from './components/access-request-queue';
import { registerMessagesHtmx } from './components/messages-htmx';
import { registerProductIdentifiersCard } from './components/product-identifiers-card';
import { registerProductLinksCard } from './components/product-links-card';
import { registerProductLifecycleCard } from './components/product-lifecycle-card';
import { registerAdminDashboardCharts } from './components/admin-dashboard-charts';

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
import { registerDocumentsTable } from '../../documents/js/documents-table';
import { registerPlanSelection } from '../../billing/js/plan-selection';
import { registerAssessmentBadge } from '../../plugins/js/assessment-badge';
import { registerAssessmentResultsCard } from '../../plugins/js/assessment-results-card';
import { registerVulnerabilityChart } from '../../vulnerability_scanning/js/vulnerability-chart';
import { registerTeamBranding, registerCustomDomain } from '../../teams/js/team-branding';
import { registerTeamGeneral } from '../../teams/js/team-general';
import { registerOnboardingWizard } from '../../teams/js/onboarding-wizard';
import { registerContactProfileForm } from '../../teams/js/components/contact-profile-form';
import { registerContactEntity } from '../../teams/js/components/contact-entity';
import { registerContactEntry } from '../../teams/js/components/contact-entry';
import { registerContactProfileList } from '../../teams/js/components/contact-profile-list';
import { setupContactProfilesUtils } from '../../teams/js/components/contact-profiles-utils';
import { registerFlashMessages } from '../../billing/js/billing';

// Track registered components to prevent double-registration
const registeredComponents = new Set<string>();

/**
 * Safely register an Alpine.data component.
 * Prevents duplicate registration.
 */
export function registerAlpineComponent(
    name: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: (...args: any[]) => any
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
export function modalState(defaultOpen: boolean = false) {
    return {
        open: defaultOpen,
        toggle(): void { this.open = !this.open; },
        show(): void { this.open = true; },
        hide(): void { this.open = false; }
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
    registerSidebar();
    registerNotificationsModal();
    registerNavbarSearch();
    registerTooltipManager();
    registerDropdownManager();
    registerModalFocusManager();
    registerCopyableValue();
    registerPublicStatusToggle();
    registerComponentVisibilitySelector();
    registerWorkspaceSwitcher();
    registerScrollTo();
    registerCollapsibleSection();
    registerAccordionItem();
    registerChartTabSelector();
    registerVulnerabilityChart();
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
    registerComponentTypeSync();
    registerMessagesToast();
    registerNotificationAutoDismiss();
    registerClipboardButton();
    registerModalFormHandler();
    registerDjangoMessages();
    registerTurnstile();
    registerFileDragAndDrop();
    registerSettingsTabs();
    registerTokenForm();
    registerVulnerabilitySettings();
    registerSbomVulnerabilitiesRefresh();
    registerAccessRequestQueue();
    registerMessagesHtmx();
    registerProductIdentifiersCard();
    registerProductLinksCard();
    registerProductLifecycleCard();
    registerAdminDashboardCharts();

    // SBOM module components
    registerSbomUpload();
    registerSbomsTable();
    registerCiCdInfo();
    registerLicensesEditor();
    registerContactsEditor();
    registerSupplierEditor();

    // Other modules
    registerDocumentUpload();
    registerDocumentsTable();
    registerPlanSelection();
    registerAssessmentBadge();
    registerAssessmentResultsCard();
    registerTeamBranding();
    registerTeamGeneral();
    registerOnboardingWizard();
    registerCustomDomain();
    registerContactProfileForm();
    registerContactEntity();
    registerContactEntry();
    registerContactProfileList();
    setupContactProfilesUtils();
    registerFlashMessages();
}

/**
 * Register components needed for HTMX bundle (subset, no releaseList/barcodes)
 */
export function registerHtmxBundleComponents(): void {
    // Common inline components
    registerCommonComponents();

    // Core components
    registerSidebar();
    registerNotificationsModal();
    registerNavbarSearch();
    registerTooltipManager();
    registerDropdownManager();
    registerModalFocusManager();
    registerCopyableValue();
    registerPublicStatusToggle();
    registerComponentVisibilitySelector();
    registerWorkspaceSwitcher();
    registerScrollTo();
    registerCollapsibleSection();
    registerAccordionItem();
    registerChartTabSelector();
    registerVulnerabilityChart();
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
    registerComponentTypeSync();
    registerMessagesToast();
    registerNotificationAutoDismiss();
    registerClipboardButton();
    registerModalFormHandler();
    registerDjangoMessages();
    registerTurnstile();
    registerFileDragAndDrop();
    registerSettingsTabs();
    registerTokenForm();
    registerVulnerabilitySettings();
    registerSbomVulnerabilitiesRefresh();
    registerAccessRequestQueue();
    registerMessagesHtmx();
    registerProductIdentifiersCard();
    registerProductLinksCard();
    registerProductLifecycleCard();
    registerAdminDashboardCharts();

    // SBOM module components
    registerSbomUpload();
    registerSbomsTable();
    registerCiCdInfo();
    registerLicensesEditor();
    registerContactsEditor();
    registerSupplierEditor();

    // Other modules
    registerDocumentUpload();
    registerDocumentsTable();
    registerPlanSelection();
    registerAssessmentBadge();
    registerAssessmentResultsCard();
    registerTeamBranding();
    registerTeamGeneral();
    registerOnboardingWizard();
    registerCustomDomain();
    registerContactProfileForm();
    registerContactEntity();
    registerContactEntry();
    registerContactProfileList();
    setupContactProfilesUtils();
    registerFlashMessages();
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
