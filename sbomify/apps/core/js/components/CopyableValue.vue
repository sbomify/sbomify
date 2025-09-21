<template>
  <span>
    <span v-if="props.value !== undefined && !props.hideValue">{{ props.value }}</span>
    <a :title="props.title ? props.title : 'Copy to clipboard'" class="ps-2" @click="copyToClipboard()">
      <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="css-i6dzq1"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
    </a>
    <span v-if="showText" class="ps-2 text-secondary copied">Copied!</span>
  </span>
</template>

<script setup lang="ts">
  import { ref } from 'vue';

  interface Props {
    value?: string;
    hideValue?: boolean;
    copyFrom?: string;
    title?: string  // html element id to copy from. Uses innerText as the value
  }

  const props = defineProps<Props>()
  const showText = ref(false);

  const displayTextFor5Seconds = () => {
    showText.value = true;
    setTimeout(() => {
      showText.value = false;
    }, 5000);
  }

  const copyToClipboard = () => {
    let valueToCopy = '';

    if (props.copyFrom) {
      const element = document.getElementById(props.copyFrom);
      if (element) {
        valueToCopy = element.innerText;
      }
    } else {
      valueToCopy = props.value || '';
    }

    navigator.clipboard.writeText(valueToCopy).then(() => {
      displayTextFor5Seconds();
    })
  };
</script>

<style scoped>
a {
  text-decoration: none;
  color: inherit;
}

.copied {
  font-size: smaller;
}

</style>

