import { createApp } from 'vue';
import PlanSelection from './components/PlanSelection.vue';
import './billing';  // Import billing utilities for notifications

// Mount the plan selection component
const planSelectionElement = document.querySelector('.vc-plan-selection');
if (planSelectionElement) {
    createApp(PlanSelection).mount(planSelectionElement);
}