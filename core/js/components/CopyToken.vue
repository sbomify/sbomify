<template>
  <div>
    <a class="btn btn-link text-white" title="Copy token" @click="copyToken">
      <i data-feather="copy"></i> Copy Access Token
    </a>
    <span v-if="showCopied" class="ps-2 text-white">Copied!</span>
  </div>
</template>

<script>
import { ref } from 'vue'

export default {
  name: 'CopyToken',
  setup() {
    const showCopied = ref(false)

    function displayCopiedFor5Seconds() {
      showCopied.value = true
      setTimeout(() => {
        showCopied.value = false
      }, 5000)
    }

    function copyToken() {
      const token = document.getElementById('access-token').innerText
      navigator.clipboard.writeText(token)
      displayCopiedFor5Seconds()
    }

    return {
      showCopied,
      copyToken
    }
  }
}
</script>