import Alpine from 'alpinejs';
import { confirmDelete } from '../utils';

interface ConfirmActionParams {
    targetElementId: string;
    confirmationMessage?: string;
    itemName: string;
    itemType: string;
}

export function registerConfirmAction() {
    Alpine.data('confirmAction', ({ targetElementId, confirmationMessage, itemName, itemType }: ConfirmActionParams) => ({
        init() {
            const elem = document.getElementById(targetElementId);

            elem?.addEventListener('click', async (event) => {
                event.preventDefault();
                const actionUrl = elem.getAttribute('href') || '';

                const confirmed = await confirmDelete({
                    itemName,
                    itemType,
                    customMessage: confirmationMessage
                });

                if (confirmed) {
                    window.location.href = actionUrl;
                }
            });
        }
    }));
}
