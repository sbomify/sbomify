import 'vite/modulepreload-polyfill';
import '../../core/js/layout-interactions';
import { registerDocumentsTable } from './documents-table';
import { registerReleaseList } from '../../core/js/components/release-list';
import { initializeAlpine } from '../../core/js/alpine-init';

registerDocumentsTable();
registerReleaseList();

void initializeAlpine();
