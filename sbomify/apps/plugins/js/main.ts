import { initAssessmentResultsCard } from './assessment-results-card'
import { initializeAlpine } from '../../core/js/alpine-init'

// A #plugin- link clicks an Alpine-bound tile, so wait for Alpine first.
void initializeAlpine().then(() => {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAssessmentResultsCard)
  } else {
    initAssessmentResultsCard()
  }
})
