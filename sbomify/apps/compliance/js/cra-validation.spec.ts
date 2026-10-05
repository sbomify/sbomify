import { describe, expect, mock, test } from 'bun:test';

mock.module('../../core/js/alpine-components', () => ({ registerAlpineComponent: () => {} }));
mock.module('./cra-shared', () => ({ getAssessmentId: () => 'test', saveStepAndNavigate: async () => {} }));

const { craStep1 } = await import('./cra-step-1');
const { craStep4 } = await import('./cra-step-4');

function readyProfile() {
  const step = craStep1();
  step.euMarkets = ['DE'];
  step.supportPeriodEnd = '2035-01-01';
  step.conformityAssessmentProcedure = 'module_a';
  return step;
}

describe('CRA required-field guidance', () => {
  test('every initial blocker has a field destination', () => {
    const step = craStep1();
    step.manufacturerIsPlaceholder = true;
    expect(step.missingFields.map(field => field.target)).toEqual([
      'manufacturer-settings', 'eu-markets', 'support-period-end', 'conformity-procedure',
    ]);
    expect(step.canContinue).toBe(false);
  });

  test('complete profile can advance without making an EU establishment determination', () => {
    const step = readyProfile();
    expect(step.euEstablished).toBe('');
    expect(step.missingFields).toEqual([]);
    expect(step.canContinue).toBe(true);
  });

  test('short support periods require a nonblank justification', () => {
    const step = readyProfile();
    step.supportPeriodMinEnd = '2036-01-01';
    step.supportPeriodShortJustification = '  ';
    expect(step.missingFields.map(field => field.target)).toEqual(['support-short-justification']);
    step.supportPeriodShortJustification = 'The product has a shorter expected lifetime.';
    expect(step.canContinue).toBe(true);
  });

  test('Class I self-assessment requires the standard confirmation', () => {
    const step = readyProfile();
    step.category = 'class_i';
    expect(step.missingFields.map(field => field.target)).toEqual(['harmonised-standard']);
    step.conformityAssessmentProcedure = 'module_b_c';
    expect(step.canContinue).toBe(true);
  });

  test('non-EU manufacturers see missing representative details before saving', () => {
    const step = readyProfile();
    step.euEstablished = 'no';
    expect(step.missingFields.map(field => field.target)).toEqual(['ar-name', 'ar-address', 'ar-email', 'ar-mandate-date']);
    step.euEstablished = 'yes';
    expect(step.canContinue).toBe(true);
  });

  test('save takes the user to the first blocker', async () => {
    const step = craStep4();
    step.focusRequiredField = mock(() => {});
    await step.save();
    expect(step.focusRequiredField).toHaveBeenCalledWith('update-method');
    expect(step.isSaving).toBe(false);
  });

  test('support portal can replace email, but whitespace cannot satisfy required fields', () => {
    const step = craStep4();
    step.updateMethod = 'Package manager';
    step.supportEmail = ' ';
    step.dataDeletionInstructions = ' ';
    expect(step.missingFields.map(field => field.target)).toEqual(['support-email', 'data-deletion']);
    step.supportUrl = 'https://example.com/support';
    step.dataDeletionInstructions = 'Remove the package and its configuration directory.';
    expect(step.canContinue).toBe(true);
  });

  test('presets retain existing answers', () => {
    const step = craStep4();
    step.updateMethod = 'Custom delivery';
    step.applyTemplate('web_app');
    expect(step.updateMethod).toBe('Custom delivery');
    expect(step.updateFrequency).toBe('regular');
  });
});
