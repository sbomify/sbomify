<template>
  <!-- The modal is now handled by SweetAlert2 -->
</template>

<script setup lang="ts">
  import { onMounted } from 'vue';
  import { confirmDelete } from '../utils';

  interface Props {
    targetElementId: string;
    confirmationMessage?: string;
    itemName: string;
    itemType: string;
  }

  const props = defineProps<Props>()

  onMounted(() => {
    const elem = document.getElementById(props.targetElementId);

    elem?.addEventListener('click', async (event) => {
      event.preventDefault();
      const actionUrl = elem.getAttribute('href') || '';

      const confirmed = await confirmDelete({
        itemName: props.itemName,
        itemType: props.itemType,
        customMessage: props.confirmationMessage
      });

      if (confirmed) {
        window.location.href = actionUrl;
      }
    });
  });
</script>
