<template>
  <StandardCard
    title="Export Data"
    :center-content="true"
    info-icon="fas fa-download"
    shadow="sm"
  >
    <p class="text-muted mb-3">Download all SBOMs associated with this project as a ZIP archive</p>
    <a class="btn btn-primary download-btn"
       :href="downloadUrl">
      <i class="fas fa-download me-2"></i>Download Project SBOMs as Zip file
    </a>
  </StandardCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StandardCard from './StandardCard.vue'

interface Props {
  projectId: string
}

const props = defineProps<Props>()

const downloadUrl = computed(() => {
  return `/sbom/download-project/${props.projectId}/`
})
</script>

<style scoped>
.download-btn {
  padding: 0.75rem 1.5rem;
  font-size: 0.9rem;
  font-weight: 500;
  border-radius: 8px;
  border: none;
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: white;
  box-shadow: 0 2px 4px rgba(99, 102, 241, 0.3);
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
}

.download-btn:hover {
  background: linear-gradient(135deg, #4f46e5, #4338ca);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
  color: white;
  text-decoration: none;
}

.download-btn:active {
  transform: translateY(0);
}
</style>