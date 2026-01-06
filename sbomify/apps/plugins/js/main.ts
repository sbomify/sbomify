import { registerAssessmentBadge } from './assessment-badge'
import { registerAssessmentResultsCard } from './assessment-results-card'
import { initializeAlpine } from '../../core/js/alpine-init'

registerAssessmentBadge()
registerAssessmentResultsCard()

void initializeAlpine()

