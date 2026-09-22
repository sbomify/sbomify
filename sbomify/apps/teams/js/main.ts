import '../../core/js/layout-interactions';
import { registerCopyableValue } from '../../core/js/components/copyable-value';
import { registerWorkspaceSwitcher } from '../../core/js/components/workspace-switcher';
import { registerSiteNotifications } from '../../core/js/components/site-notifications';
import { registerOnboardingWizard } from './onboarding-wizard';
import { initializeAlpine } from '../../core/js/alpine-init';

registerCopyableValue();
registerWorkspaceSwitcher();
registerSiteNotifications();
registerOnboardingWizard();
initializeAlpine();
