import 'vite/modulepreload-polyfill';
import '../../core/js/bootstrap-init';
import { initializeAlpine } from '../../core/js/alpine-init';

/**
 * Documents Module JavaScript Entry Point
 * 
 * NOTE: All Alpine components are registered in the central registry
 * (core/js/alpine-components.ts) and loaded via htmx-bundle.ts.
 * 
 * Components registered in central registry:
 * - registerDocumentsTable
 * - registerReleaseList
 * - registerDocumentUpload
 */

void initializeAlpine();
