<template>
  <StandardCard
    :title="title || 'Download'"
    variant="default"
    shadow="sm"
  >
    <div class="text-center">
      <p v-if="description" class="text-muted mb-3">{{ description }}</p>
      <a
        :href="downloadUrl"
        class="btn btn-primary download-btn"
        @click="handleDownload"
      >
        <i v-if="downloadIcon" :class="downloadIcon" class="me-2"></i>
        {{ downloadText || 'Download' }}
      </a>
      <div v-if="fileInfo" class="file-info mt-2">
        <small class="text-muted">{{ fileInfo }}</small>
      </div>
      <div v-if="additionalInfo" class="additional-info mt-2">
        <small class="text-muted">{{ additionalInfo }}</small>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import StandardCard from './StandardCard.vue'

interface Props {
  title?: string
  description?: string
  downloadUrl: string
  downloadText?: string
  downloadIcon?: string
  fileInfo?: string
  additionalInfo?: string
  downloadCount?: number
}

withDefaults(defineProps<Props>(), {
  title: 'Download',
  description: '',
  downloadText: 'Download',
  downloadIcon: 'fas fa-download',
  fileInfo: '',
  additionalInfo: ''
})

const emit = defineEmits<{
  download: []
}>()

const handleDownload = () => {
  emit('download')
}
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
  text-decoration: none;
}

.download-btn:hover {
  background: linear-gradient(135deg, #4f46e5, #4338ca);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
  color: white;
  text-decoration: none;
}

.file-info,
.additional-info {
  font-size: 0.875rem;
}
</style>