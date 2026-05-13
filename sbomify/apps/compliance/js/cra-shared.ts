import { getCsrfToken } from '../../core/js/csrf';
import { showError } from '../../core/js/alerts';

/**
 * Read assessment ID from the assessment-meta json_script block.
 */
export function getAssessmentId(): string {
  const meta = window.parseJsonScript('assessment-meta') as Record<string, string> | null;
  return meta?.id || '';
}

/**
 * Read step URLs from the step-urls json_script block.
 */
export function getStepUrls(): Record<string, string> {
  return (window.parseJsonScript('step-urls') as Record<string, string>) || {};
}

/**
 * Save step data and navigate to the next step.
 */
export async function saveStepAndNavigate(
  assessmentId: string,
  step: number,
  data: Record<string, unknown>,
  setLoading: (v: boolean) => void,
): Promise<void> {
  setLoading(true);
  try {
    const resp = await fetch(`/api/v1/compliance/cra/${assessmentId}/step/${step}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ data }),
    });
    if (resp.ok) {
      const stepUrls = getStepUrls();
      const nextStep = step + 1;
      const nextUrl = stepUrls[String(nextStep)] || `/compliance/cra/${assessmentId}/step/${nextStep}/`;
      window.location.href = nextUrl;
    } else {
      const err = await resp.json();
      showError(err.error || 'Failed to save');
    }
  } catch {
    showError('Network error — please try again');
  } finally {
    setLoading(false);
  }
}
