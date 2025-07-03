<template>
  <StandardCard
    title="SBOM Description"
    info-icon="fas fa-comment-alt"
    shadow="sm"
    :collapsible="true"
    :default-expanded="true"
    storage-key="sbom-comment"
  >
    <div v-if="props.comment && props.comment.trim()" class="comment-content">
      <p class="comment-text">{{ props.comment }}</p>
    </div>
    <div v-else class="no-comment">
      <i class="fas fa-info-circle me-2 text-muted"></i>
      <span class="text-muted">No description provided for this SBOM.</span>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import StandardCard from '../../../core/js/components/StandardCard.vue'

interface Props {
  comment?: string
}

const props = defineProps<Props>()
</script>

<style scoped>
.comment-content {
  line-height: 1.6;
}

.comment-text {
  margin: 0;
  color: #374151;
  font-size: 0.9rem;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.no-comment {
  display: flex;
  align-items: center;
  padding: 1rem 0;
  font-style: italic;
  font-size: 0.9rem;
}
</style>