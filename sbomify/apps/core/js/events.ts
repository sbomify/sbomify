/**
 * Centralized event definitions for component communication
 * All custom events should be defined here with their payload types
 */

import type { ContactInfo, ComponentMetaInfo } from './types';

export const ComponentEvents = {
    METADATA_LOADED: 'component:metadata:loaded',
    METADATA_UPDATED: 'component:metadata:updated',
    METADATA_SAVED: 'component:metadata:saved',
    AUTHORS_UPDATED: 'component:authors:updated',
    CONTACTS_UPDATED: 'component:contacts:updated',
    SHOW_ALERT: 'component:show:alert',
} as const;

export interface MetadataLoadedEvent {
    metadata: ComponentMetaInfo;
    licenses: ComponentMetaInfo['licenses'];
    supplier: ComponentMetaInfo['supplier'];
    authors: ContactInfo[];
}

export interface AuthorsUpdatedEvent {
    authors: ContactInfo[];
}

export interface ContactsUpdatedEvent {
    contacts: ContactInfo[];
}

export interface MetadataUpdatedEvent {
    componentId: string;
}

export interface ShowAlertEvent {
    type: 'success' | 'error' | 'warning' | 'info';
    message: string;
}

/**
 * Type-safe event dispatcher
 */
export function dispatchComponentEvent<T>(eventName: string, detail: T): void {
    window.dispatchEvent(new CustomEvent(eventName, { detail }));
}

/**
 * Type-safe event listener
 */
export function addComponentEventListener<T>(
    eventName: string,
    handler: (event: CustomEvent<T>) => void
): () => void {
    const typedHandler = handler as EventListener;
    window.addEventListener(eventName, typedHandler);
    
    // Return cleanup function
    return () => window.removeEventListener(eventName, typedHandler);
}
