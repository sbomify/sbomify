import * as bootstrap from 'bootstrap';
import './layout-interactions';
import './alerts-global';
import './clipboard-global';
import './navbar-search';
import { registerDeleteModal } from './components/delete-modal';
import { registerWorkspaceSwitcher } from './components/workspace-switcher';
import { registerCopyableValue } from './components/copyable-value';
import { registerPublicStatusToggle } from './components/public-status-toggle';
import { initializeAlpine } from './alpine-init';

registerCopyableValue();
registerPublicStatusToggle();
registerWorkspaceSwitcher();
registerDeleteModal();
initializeAlpine();

// Expose bootstrap globally
declare global {
    interface Window {
        bootstrap: typeof bootstrap;
    }
}

window.bootstrap = bootstrap;
