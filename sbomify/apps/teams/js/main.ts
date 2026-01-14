import 'vite/modulepreload-polyfill';
import '../../core/js/layout-interactions';
import { registerTeamBranding, registerCustomDomain } from './team-branding';
import { registerCopyableValue } from '../../core/js/components/copyable-value';
import { registerFileDragAndDrop } from '../../core/js/components/file-drag-and-drop';
import { registerWorkspaceSwitcher } from '../../core/js/components/workspace-switcher';
import { registerOnboardingWizard } from './onboarding-wizard';
import { registerTeamGeneral } from './team-general';
import { initializeAlpine } from '../../core/js/alpine-init';

registerCopyableValue();
registerFileDragAndDrop();
registerWorkspaceSwitcher();
registerTeamBranding();
registerCustomDomain();
registerOnboardingWizard();
registerTeamGeneral();
initializeAlpine();
