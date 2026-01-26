/**
 * TypeScript interfaces and type guards for Alpine.js components
 * 
 * These types help ensure components follow standardization patterns
 * for cleanup and resource management.
 */

/**
 * Base interface for Alpine.js components
 */
export interface AlpineComponent {
    $el: HTMLElement;
    $refs?: { [key: string]: HTMLElement };
    $store?: AlpineStores;
    $nextTick?: (callback: () => void) => void;
    $watch?: (property: string, callback: (newValue: unknown, oldValue?: unknown) => void) => void;
    $dispatch?: (event: string, detail?: unknown) => void;
    init?: () => void;
    destroy?: () => void;
    [key: string]: unknown; // Index signature for Alpine component properties
}

/**
 * Alpine Stores type (from global declarations)
 */
interface AlpineStores {
    sidebar: {
        open: boolean;
        toggle(): void;
        close(): void;
    };
    alerts: {
        showSuccess(message: string): void;
        showError(message: string): void;
        showWarning(message: string): void;
        showInfo(message: string): void;
        showToast(options: {
            title: string;
            message: string;
            type: 'success' | 'error' | 'warning' | 'info';
            timer?: number;
            position?: 'top-end' | 'top' | 'top-start' | 'center' | 'bottom' | 'bottom-end' | 'bottom-start';
        }): void;
        showConfirmation(options: {
            title?: string;
            message: string;
            confirmButtonText?: string;
            cancelButtonText?: string;
            type?: 'success' | 'error' | 'warning' | 'info';
        }): Promise<boolean>;
    };
    clipboard: {
        copy(text: string, successMessage?: string, errorMessage?: string): Promise<void>;
        initButtons(container?: HTMLElement | Document): void;
    };
    modals: {
        triggerElements: Record<string, HTMLElement>;
        observers: Map<string, { intersectionObserver: IntersectionObserver; mutationObserver: MutationObserver }>;
        getFocusableElements(container: HTMLElement): HTMLElement[];
        handleTabKey(event: KeyboardEvent, modalElement: HTMLElement): void;
        handleModalOpen(modalElement: HTMLElement, modalId: string): void;
        handleModalClose(modalId: string): void;
        initModal(modalId: string, overlay: HTMLElement): void;
    };
    charts: {
        initVulnerabilityChart(container: HTMLElement, chartType: string): Promise<void>;
    };
}

/**
 * Component that has a destroy method for cleanup
 */
export interface ComponentWithDestroy extends AlpineComponent {
    destroy: () => void;
}

/**
 * Component that uses timers (setTimeout or setInterval)
 */
export interface ComponentWithTimers extends AlpineComponent {
    timer?: ReturnType<typeof setTimeout> | null;
    intervalId?: ReturnType<typeof setInterval> | null;
    searchTimeout?: ReturnType<typeof setTimeout> | null;
    destroy?: () => void;
}

/**
 * Component that uses observers (IntersectionObserver or MutationObserver)
 */
export interface ComponentWithObservers extends AlpineComponent {
    observer?: IntersectionObserver | MutationObserver | null;
    intersectionObserver?: IntersectionObserver | null;
    mutationObserver?: MutationObserver | null;
    destroy?: () => void;
}

/**
 * Component that uses global event listeners
 */
export interface ComponentWithGlobalListeners extends AlpineComponent {
    listener?: EventListener | null;
    listeners?: Array<{ event: string; listener: EventListener }>;
    destroy?: () => void;
}

/**
 * Component that uses external resources (charts, third-party libraries)
 */
export interface ComponentWithExternalResources extends AlpineComponent {
    chartInstance?: { destroy: () => void } | null;
    externalResource?: { cleanup?: () => void; destroy?: () => void } | null;
    destroy?: () => void;
}

/**
 * Type guard to check if component has destroy method
 */
export function hasDestroyMethod(component: AlpineComponent): component is ComponentWithDestroy {
    return typeof component.destroy === 'function';
}

/**
 * Type guard to check if component uses timers
 */
export function hasTimers(component: AlpineComponent): component is ComponentWithTimers {
    return (
        (component as ComponentWithTimers).timer !== undefined ||
        (component as ComponentWithTimers).intervalId !== undefined ||
        (component as ComponentWithTimers).searchTimeout !== undefined
    );
}

/**
 * Type guard to check if component uses observers
 */
export function hasObservers(component: AlpineComponent): component is ComponentWithObservers {
    return (
        (component as ComponentWithObservers).observer !== undefined ||
        (component as ComponentWithObservers).intersectionObserver !== undefined ||
        (component as ComponentWithObservers).mutationObserver !== undefined
    );
}

/**
 * Type guard to check if component uses global listeners
 */
export function hasGlobalListeners(component: AlpineComponent): component is ComponentWithGlobalListeners {
    return (
        (component as ComponentWithGlobalListeners).listener !== undefined ||
        (component as ComponentWithGlobalListeners).listeners !== undefined
    );
}

/**
 * Type guard to check if component uses external resources
 */
export function hasExternalResources(component: AlpineComponent): component is ComponentWithExternalResources {
    return (
        (component as ComponentWithExternalResources).chartInstance !== undefined ||
        (component as ComponentWithExternalResources).externalResource !== undefined
    );
}

/**
 * Verify that a component with timers has a destroy method
 */
export function verifyTimerCleanup(component: ComponentWithTimers): boolean {
    if (hasTimers(component)) {
        return hasDestroyMethod(component);
    }
    return true; // No timers, no cleanup needed
}

/**
 * Verify that a component with observers has a destroy method
 */
export function verifyObserverCleanup(component: ComponentWithObservers): boolean {
    if (hasObservers(component)) {
        return hasDestroyMethod(component);
    }
    return true; // No observers, no cleanup needed
}

/**
 * Verify that a component with global listeners has a destroy method
 */
export function verifyListenerCleanup(component: ComponentWithGlobalListeners): boolean {
    if (hasGlobalListeners(component)) {
        return hasDestroyMethod(component);
    }
    return true; // No global listeners, no cleanup needed
}
