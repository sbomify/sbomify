import { afterEach, beforeEach, describe, test, expect, mock } from 'bun:test';

mock.module('alpinejs', () => ({ default: { data: mock() } }));
const { onboardingWizard } = await import('./onboarding-wizard');

const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
beforeEach(() => {
    globalThis.requestAnimationFrame = callback => { callback(0); return 1; };
});
afterEach(() => { globalThis.requestAnimationFrame = originalRequestAnimationFrame; });

function build() {
    const organisationField = { disabled: false, checkValidity: mock(() => true), reportValidity: mock() };
    const securityField = { disabled: false, checkValidity: mock(() => true), reportValidity: mock() };
    const refs = {
        organisation: { querySelectorAll: () => [organisationField] },
        security: { querySelectorAll: () => [securityField] },
        email: { value: 'author@example.com' },
        securityEmail: { value: '' },
        organisationTitle: { focus: mock(), scrollIntoView: mock() },
        securityTitle: { focus: mock(), scrollIntoView: mock() },
    };
    const wizard = Object.assign(onboardingWizard({ step: 'organisation', addressExpanded: false }), {
        $refs: refs,
        $nextTick: (callback: () => void) => callback(),
    });
    return { wizard, refs, organisationField, securityField };
}

function submitEvent() {
    return { preventDefault: mock() } as unknown as SubmitEvent;
}

describe('Onboarding flow', () => {
    test('validates organisation before advancing and supplies the contact suggestion', () => {
        const { wizard, refs, organisationField } = build();
        organisationField.checkValidity.mockReturnValue(false);
        wizard.next();
        expect(wizard.step).toBe('organisation');
        expect(organisationField.reportValidity).toHaveBeenCalled();
        organisationField.checkValidity.mockReturnValue(true);
        wizard.next();
        expect(wizard.step).toBe('security');
        expect(refs.securityEmail.value).toBe('author@example.com');
        expect(refs.securityTitle.focus).toHaveBeenCalled();
        expect(refs.securityTitle.scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'instant' });
    });

    test('Back retains a separately chosen security email', () => {
        const { wizard, refs } = build();
        wizard.next();
        refs.securityEmail.value = 'security@example.com';
        wizard.back();
        expect(refs.organisationTitle.scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'instant' });
        refs.email.value = 'new-author@example.com';
        wizard.next();
        expect(refs.securityEmail.value).toBe('security@example.com');
        expect(refs.organisationTitle.focus).toHaveBeenCalled();
    });

    test('Enter on the organisation step advances without saving', () => {
        const { wizard } = build();
        const event = submitEvent();
        wizard.submit(event);
        expect(event.preventDefault).toHaveBeenCalled();
        expect(wizard.step).toBe('security');
        expect(wizard.isSubmitting).toBe(false);
    });

    test('returns to the relevant step for an invalid control and blocks duplicate saves', () => {
        const { wizard, organisationField, securityField } = build();
        wizard.next();
        organisationField.checkValidity.mockReturnValue(false);
        const invalid = submitEvent();
        wizard.submit(invalid);
        expect(invalid.preventDefault).toHaveBeenCalled();
        expect(wizard.step).toBe('organisation');
        organisationField.checkValidity.mockReturnValue(true);
        wizard.next();
        securityField.checkValidity.mockReturnValue(false);
        wizard.submit(submitEvent());
        expect(wizard.isSubmitting).toBe(false);
        expect(securityField.reportValidity).toHaveBeenCalled();
        securityField.checkValidity.mockReturnValue(true);
        const valid = submitEvent();
        wizard.submit(valid);
        expect(valid.preventDefault).not.toHaveBeenCalled();
        expect(wizard.isSubmitting).toBe(true);
        const duplicate = submitEvent();
        wizard.submit(duplicate);
        expect(duplicate.preventDefault).toHaveBeenCalled();
    });
});
