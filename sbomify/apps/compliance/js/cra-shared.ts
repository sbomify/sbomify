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
      window.location.href = `/compliance/cra/${assessmentId}/step/${step + 1}/`;
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
