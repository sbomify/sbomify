import { registerAssessmentBadge } from './assessment-badge'
import { initAssessmentResultsCard } from './assessment-results-card'
import { initializeAlpine } from '../../core/js/alpine-init'

registerAssessmentBadge()

// Initialize assessment results card (handles anchor navigation)
document.addEventListener('DOMContentLoaded', initAssessmentResultsCard)

void initializeAlpine()

