import { describe, it, expect } from 'bun:test';
import planSelection from './plan-selection';

describe('planSelection', () => {
    const mockData = {
        currentPlan: 'community',
        csrfToken: 'token',
        enterpriseContactUrl: '/contact',
    };

    it('initializes with correct defaults', () => {
        const vm = planSelection(mockData);
        expect(vm.billingPeriod).toBe('monthly');
        expect(vm.currentPlan).toBe('community');
    });

    it('keeps current and scheduled Community actions disabled independently of their labels', () => {
        const current = planSelection(mockData);
        current.getButtonText = () => 'A different label';
        expect(current.canSelectPlan('community')).toBe(false);
        expect(current.canSelectPlan('business')).toBe(true);
        current.handlePlanSelection('community');
        expect(current.isSubmitting).toBe(false);

        const scheduled = planSelection({ ...mockData, currentPlan: 'business', cancelAtPeriodEnd: true });
        expect(scheduled.canSelectPlan('community')).toBe(false);
        expect(scheduled.canSelectPlan('business')).toBe(true);
    });

    it('blocks plans over their limits and repeated submissions', () => {
        const vm = planSelection({
            ...mockData, currentPlan: 'business',
            downgradeLimits: { community: { exceeds: true, resources: ['2 products (limit: 1)'] } },
        });
        expect(vm.canSelectPlan('community')).toBe(false);
        vm.handlePlanSelection('community');
        expect(vm.isSubmitting).toBe(false);
        vm.isSubmitting = true;
        expect(vm.canSelectPlan('business')).toBe(false);
        expect(vm.canSelectPlan('enterprise')).toBe(false);
    });

    describe('getButtonText', () => {
        it('returns "Current plan" for current plan', () => {
            const vm = planSelection(mockData);
            expect(vm.getButtonText('community')).toBe('Current plan');
        });

        it('returns "Contact sales" for enterprise', () => {
            const vm = planSelection(mockData);
            expect(vm.getButtonText('enterprise')).toBe('Contact sales');
        });

        it('returns "Select plan" for other plans when current plan exists', () => {
            const vm = planSelection(mockData);
            expect(vm.getButtonText('business')).toBe('Select plan');
        });

        it('returns "Get started" when no current plan (corner case)', () => {
            const vm = planSelection({ ...mockData, currentPlan: '' });
            expect(vm.getButtonText('business')).toBe('Get started');
        });
    });
});
