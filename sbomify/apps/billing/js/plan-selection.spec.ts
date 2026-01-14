import { describe, it, expect } from 'bun:test';
import planSelection from './plan-selection';

describe('planSelection', () => {
    const mockData = {
        currentPlan: 'community',
        teamKey: 'test-team',
        usage: { users: 1, products: 5, projects: 5, components: 50 },
        csrfToken: 'token',
        enterpriseContactUrl: '/contact',
    };

    it('initializes with correct defaults', () => {
        const vm = planSelection(mockData);
        expect(vm.billingPeriod).toBe('monthly');
        expect(vm.currentPlan).toBe('community');
        expect(vm.usage).toEqual(mockData.usage);
    });

    it('returns correct features for community plan', () => {
        const vm = planSelection(mockData);
        const features = vm.getFeatures('community');
        expect(features).toContainEqual({ key: 'user-limit', label: '1 user (owner only)' });
    });

    describe('getButtonText', () => {
        it('returns "Current Plan" for current plan', () => {
            const vm = planSelection(mockData);
            expect(vm.getButtonText('community')).toBe('Current Plan');
        });

        it('returns "Contact Sales" for enterprise', () => {
            const vm = planSelection(mockData);
            expect(vm.getButtonText('enterprise')).toBe('Contact Sales');
        });

        it('returns "Switch to This Plan" for other plans when current plan exists', () => {
            const vm = planSelection(mockData);
            expect(vm.getButtonText('business')).toBe('Switch to This Plan');
        });

        it('returns "Get Started" when no current plan (corner case)', () => {
            const vm = planSelection({ ...mockData, currentPlan: '' });
            expect(vm.getButtonText('business')).toBe('Get Started');
        });
    });
});
