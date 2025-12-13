import 'vite/modulepreload-polyfill';
import '../../core/js/layout-interactions';
import Alpine from 'alpinejs';
import { registerTeamBranding, registerCustomDomain } from './team-branding';
import { registerCopyableValue } from '../../core/js/components/copyable-value';
import { registerFileDragAndDrop } from '../../core/js/components/file-drag-and-drop';
import { registerOnboardingWizard } from './onboarding-wizard';
import { registerTeamGeneral } from './team-general';

document.addEventListener('alpine:init', () => {
    registerCopyableValue();
    registerFileDragAndDrop();
    registerTeamBranding();
    registerCustomDomain();
    registerOnboardingWizard();
    registerTeamGeneral();
});

Alpine.start();
