/**
 * A stand-in for every export of cra-shared, for specs that mock it.
 *
 * bun keeps a module mock for the rest of the run, so a spec that mocks
 * cra-shared with fewer exports than the real module breaks the next spec whose
 * code imports the missing one ("Export named ... not found"). Mocking through
 * this keeps every export present, whichever spec ran first.
 */
export function craSharedMock(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    getAssessmentId: () => 'test-assessment-id',
    getStepUrls: () => ({}),
    saveStepAndNavigate: async () => {},
    ...overrides,
  };
}
