import { describe, test, expect, mock, beforeEach } from 'bun:test';
import type { Finding } from './cra-step-3';

// Stub module-level imports BEFORE the dynamic import of `cra-step-3` so
// importing it does not drag in the full Alpine/plugins tree and does not
// require a live DOM / MutationObserver.
mock.module('../../core/js/alpine-components', () => ({
  registerAlpineComponent: () => {},
}));
mock.module('../../core/js/csrf', () => ({
  getCsrfToken: () => 'test-csrf-token',
}));
mock.module('../../core/js/alerts', () => ({
  showError: () => {},
}));
mock.module('./cra-shared', () => ({
  getAssessmentId: () => 'test-assessment-id',
  saveStepAndNavigate: async () => {},
}));

const { craStep3 } = await import('./cra-step-3');

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    finding_id: 'f-1',
    control_id: 'cra-sd-1',
    title: 'Test control',
    description: '',
    status: 'unanswered',
    notes: '',
    justification: '',
    is_mandatory: false,
    annex_part: 'Part I',
    annex_reference: 'Annex I, Part I, §1',
    annex_url: 'https://eur-lex.europa.eu/...',
    ...overrides,
  };
}

describe('craStep3 — _pendingNA state machine (regression for stale-highlight bug)', () => {
  let comp: ReturnType<typeof craStep3>;

  beforeEach(() => {
    comp = craStep3();
    comp.assessmentId = 'test-assessment-id';
  });

  test('clicking N/A on a non-mandatory Part I without justification sets _pendingNA and leaves finding.status untouched', async () => {
    const finding = makeFinding({ status: 'satisfied', is_mandatory: false, justification: '' });

    await comp.setFindingStatus(finding, 'not-applicable');

    expect(comp._pendingNA[finding.finding_id]).toBe(true);
    expect(finding.status).toBe('satisfied');
  });

  test('buttonState resolves to pending-na while _pendingNA is set, regardless of prior status', async () => {
    const finding = makeFinding({ status: 'satisfied' });
    await comp.setFindingStatus(finding, 'not-applicable');

    expect(comp.buttonState(finding)).toBe('pending-na');

    const fromNotSatisfied = makeFinding({ finding_id: 'f-2', status: 'not-satisfied' });
    await comp.setFindingStatus(fromNotSatisfied, 'not-applicable');
    expect(comp.buttonState(fromNotSatisfied)).toBe('pending-na');
  });

  test('buttonState returns the stored status once _pendingNA clears', () => {
    const finding = makeFinding({ status: 'satisfied' });
    expect(comp.buttonState(finding)).toBe('satisfied');

    const notSat = makeFinding({ status: 'not-satisfied' });
    expect(comp.buttonState(notSat)).toBe('not-satisfied');

    const na = makeFinding({ status: 'not-applicable', justification: 'valid' });
    expect(comp.buttonState(na)).toBe('not-applicable');

    const unanswered = makeFinding({ status: 'unanswered' });
    expect(comp.buttonState(unanswered)).toBe('unanswered');

    const weird = makeFinding({ status: 'something-unexpected' });
    expect(comp.buttonState(weird)).toBe('unanswered');
  });

  test('showJustificationField is true while _pendingNA is set on a non-mandatory Part I', async () => {
    const finding = makeFinding({ status: 'satisfied', is_mandatory: false });
    await comp.setFindingStatus(finding, 'not-applicable');

    expect(comp.showJustificationField(finding)).toBe(true);
  });

  test('mandatory Part II controls ignore the N/A click — no _pendingNA, no status change', async () => {
    const finding = makeFinding({ status: 'satisfied', is_mandatory: true, annex_part: 'Part II' });

    await comp.setFindingStatus(finding, 'not-applicable');

    expect(comp._pendingNA[finding.finding_id]).toBeUndefined();
    expect(finding.status).toBe('satisfied');
  });

  test('Part I N/A commits immediately when a justification is already present — no pending flag', async () => {
    const finding = makeFinding({ status: 'satisfied', is_mandatory: false, justification: 'feature absent' });
    const fetchStub = mock(async () => new Response(null, { status: 200 }));
    (globalThis as { fetch: typeof fetch }).fetch = fetchStub as unknown as typeof fetch;

    await comp.setFindingStatus(finding, 'not-applicable');

    expect(comp._pendingNA[finding.finding_id]).toBeUndefined();
    expect(finding.status).toBe('not-applicable');
  });

  test('setFindingStatus rolls back BOTH finding.status AND _pendingNA on PUT failure', async () => {
    const finding = makeFinding({ status: 'satisfied', is_mandatory: false });
    await comp.setFindingStatus(finding, 'not-applicable');
    expect(comp._pendingNA[finding.finding_id]).toBe(true);

    const fetchStub = mock(async () => new Response(JSON.stringify({ error: 'boom' }), { status: 500 }));
    (globalThis as { fetch: typeof fetch }).fetch = fetchStub as unknown as typeof fetch;

    await comp.setFindingStatus(finding, 'satisfied');

    expect(finding.status).toBe('satisfied');
    expect(comp._pendingNA[finding.finding_id]).toBe(true);
  });
});
