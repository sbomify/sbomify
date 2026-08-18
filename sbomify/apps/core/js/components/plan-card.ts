import Alpine from 'alpinejs';

interface PlanCardParams {
    isCurrentPlan: boolean;
    buttonDisabled: boolean;
    loading: boolean;
    buttonVariant?: 'primary' | 'secondary' | 'outline-primary' | 'outline-secondary' | 'success' | 'danger';
}

export function registerPlanCard() {
    Alpine.data('planCard', ({ isCurrentPlan, buttonDisabled, loading, buttonVariant = 'primary' }: PlanCardParams) => ({
        isCurrentPlan,
        buttonDisabled,
        loading,
        buttonVariant,

        get buttonClasses(): string {
            const classes: string[] = [];

            if (this.isCurrentPlan) {
                classes.push('tw-btn-outline');
            } else {
                switch (this.buttonVariant) {
                    case 'primary':
                        classes.push('tw-btn-primary');
                        break;
                    case 'secondary':
                        classes.push('tw-btn-secondary');
                        break;
                    case 'outline-primary':
                        classes.push('tw-btn-outline-primary');
                        break;
                    case 'outline-secondary':
                        classes.push('tw-btn-outline');
                        break;
                    case 'success':
                        classes.push('tw-btn-success');
                        break;
                    case 'danger':
                        classes.push('tw-btn-danger');
                        break;
                    default:
                        classes.push('tw-btn-primary');
                }
            }

            if (this.loading) {
                classes.push('tw-btn-loading');
            }

            return classes.join(' ');
        },

        get isButtonDisabled(): boolean {
            return this.buttonDisabled || this.loading || this.isCurrentPlan;
        },

        handleAction() {
            if (!this.isButtonDisabled) {
                this.$dispatch('plan-action');
            }
        }
    }));
}
