/**
 * Centralized event definitions for component communication
 * All custom events should be defined here with their payload types
 */

import type { ContactInfo, ComponentMetaInfo } from './types';

export const ComponentEvents = {
    METADATA_LOADED: 'component:metadata:loaded',
} as const;

export interface MetadataLoadedEvent {
    metadata: ComponentMetaInfo;
    licenses: ComponentMetaInfo['licenses'];
    supplier: ComponentMetaInfo['supplier'];
    authors: ContactInfo[];
}

/**
 * Type-safe event dispatcher
 */
export function dispatchComponentEvent<T>(eventName: string, detail: T): void {
    window.dispatchEvent(new CustomEvent(eventName, { detail }));
}
