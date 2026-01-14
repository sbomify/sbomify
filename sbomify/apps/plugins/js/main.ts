import { registerAssessmentBadge } from './assessment-badge'
import { initAssessmentResultsCard } from './assessment-results-card'
import { registerSiteNotifications } from '../../core/js/components/site-notifications'
import { initializeAlpine } from '../../core/js/alpine-init'

registerAssessmentBadge()
registerSiteNotifications()

// Initialize assessment results card (handles anchor navigation)
document.addEventListener('DOMContentLoaded', initAssessmentResultsCard)

void initializeAlpine()

