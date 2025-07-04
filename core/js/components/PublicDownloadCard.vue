<template>
  <PublicCard
    :title="title"
    :subtitle="subtitle"
    :icon="icon"
    variant="primary"
    size="md"
    hoverable
    class="public-download-card"
  >
    <template #header>
      <div class="download-actions">
        <button
          v-if="downloadUrl"
          :disabled="isDownloading"
          class="download-btn download-btn--primary"
          @click="handleDownload"
        >
          <i v-if="!isDownloading" :class="downloadIcon" class="download-icon"></i>
          <div v-else class="download-spinner"></div>
          <span>{{ isDownloading ? 'Downloading...' : downloadText }}</span>
        </button>
      </div>
    </template>

    <div class="download-content">
      <!-- Description -->
      <div v-if="description" class="download-description">
        <p>{{ description }}</p>
      </div>

      <!-- File Info -->
      <div v-if="fileInfo" class="download-file-info">
        <div class="file-info-grid">
          <div v-if="fileInfo.size" class="file-info-item">
            <i class="fas fa-hdd file-info-icon"></i>
            <span class="file-info-label">Size</span>
            <span class="file-info-value">{{ formatFileSize(fileInfo.size) }}</span>
          </div>
          <div v-if="fileInfo.type" class="file-info-item">
            <i class="fas fa-file-alt file-info-icon"></i>
            <span class="file-info-label">Type</span>
            <span class="file-info-value">{{ fileInfo.type }}</span>
          </div>
          <div v-if="fileInfo.lastModified" class="file-info-item">
            <i class="fas fa-clock file-info-icon"></i>
            <span class="file-info-label">Modified</span>
            <span class="file-info-value">{{ formatDate(fileInfo.lastModified) }}</span>
          </div>
        </div>
      </div>

      <!-- Additional Info -->
      <div v-if="additionalInfo && additionalInfo.length > 0" class="download-additional-info">
        <div class="additional-info-list">
          <div v-for="(info, index) in additionalInfo" :key="index" class="additional-info-item">
            <i v-if="info.icon" :class="info.icon" class="additional-info-icon"></i>
            <span class="additional-info-text">{{ info.text }}</span>
          </div>
        </div>
      </div>

      <!-- Secondary Actions -->
      <div v-if="secondaryActions && secondaryActions.length > 0" class="download-secondary-actions">
                  <button
            v-for="action in secondaryActions"
            :key="action.id"
            :disabled="action.disabled"
            class="download-btn download-btn--secondary"
            @click="handleSecondaryAction(action)"
          >
          <i v-if="action.icon" :class="action.icon" class="download-icon"></i>
          <span>{{ action.text }}</span>
        </button>
      </div>
    </div>

    <template #footer>
      <div class="download-footer">
        <div class="download-footer-info">
          <i class="fas fa-shield-alt footer-icon"></i>
          <span class="footer-text">Secure download</span>
        </div>
        <div v-if="downloadCount" class="download-stats">
          <i class="fas fa-download stats-icon"></i>
          <span class="stats-text">{{ downloadCount }} downloads</span>
        </div>
      </div>
    </template>
  </PublicCard>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import PublicCard from './PublicCard.vue'

interface FileInfo {
  size?: number
  type?: string
  lastModified?: string
}

interface AdditionalInfo {
  icon?: string
  text: string
}

interface SecondaryAction {
  id: string
  text: string
  icon?: string
  disabled?: boolean
  action: () => void
}

interface Props {
  title?: string
  subtitle?: string
  icon?: string
  description?: string
  downloadUrl?: string
  downloadText?: string
  downloadIcon?: string
  fileInfo?: FileInfo
  additionalInfo?: AdditionalInfo[]
  secondaryActions?: SecondaryAction[]
  downloadCount?: number
}

const props = withDefaults(defineProps<Props>(), {
  title: 'Download',
  subtitle: '',
  icon: 'fas fa-download',
  description: '',
  downloadUrl: '',
  downloadText: 'Download',
  downloadIcon: 'fas fa-download',
  fileInfo: undefined,
  additionalInfo: () => [],
  secondaryActions: () => [],
  downloadCount: 0
})

const emit = defineEmits<{
  download: [url: string]
  secondaryAction: [action: SecondaryAction]
}>()

const isDownloading = ref(false)

const handleDownload = async () => {
  if (!props.downloadUrl || isDownloading.value) return

  isDownloading.value = true

  try {
    emit('download', props.downloadUrl)

    // Create download link
    const link = document.createElement('a')
    link.href = props.downloadUrl
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // Reset downloading state after a delay
    setTimeout(() => {
      isDownloading.value = false
    }, 1000)
  } catch (error) {
    console.error('Download failed:', error)
    isDownloading.value = false
  }
}

const handleSecondaryAction = (action: SecondaryAction) => {
  if (action.disabled) return
  emit('secondaryAction', action)
  action.action()
}

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

const formatDate = (dateString: string): string => {
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}
</script>

<style scoped>
.public-download-card {
  --download-primary-color: var(--brand-color);
  --download-secondary-color: var(--accent-color);
}

/* Download Actions */
.download-actions {
  display: flex;
  gap: 0.5rem;
}

.download-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: var(--radius-md);
  font-weight: 500;
  text-decoration: none;
  transition: all 0.2s ease;
  cursor: pointer;
  font-size: 0.875rem;
  white-space: nowrap;
}

.download-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.download-btn--primary {
  background: rgba(255, 255, 255, 0.15);
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.25);
  backdrop-filter: blur(8px);
}

.download-btn--primary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.25);
  border-color: rgba(255, 255, 255, 0.4);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.download-btn--secondary {
  background: var(--bg-primary);
  color: var(--download-secondary-color);
  border: 1px solid var(--download-secondary-color);
}

.download-btn--secondary:hover:not(:disabled) {
  background: var(--download-secondary-color);
  color: white;
  transform: translateY(-1px);
}

.download-icon {
  font-size: 0.875rem;
}

.download-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top: 2px solid white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* Download Content */
.download-content {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.download-description {
  color: var(--text-secondary);
  line-height: 1.6;
}

.download-description p {
  margin: 0;
}

/* File Info */
.download-file-info {
  background: var(--bg-tertiary);
  border-radius: var(--radius-md);
  padding: 1rem;
  border: 1px solid var(--border-color);
}

.file-info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.file-info-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.file-info-icon {
  color: var(--download-primary-color);
  font-size: 0.875rem;
  width: 16px;
  text-align: center;
}

.file-info-label {
  font-weight: 500;
  color: var(--text-secondary);
  min-width: 60px;
}

.file-info-value {
  color: var(--text-primary);
  font-weight: 500;
}

/* Additional Info */
.download-additional-info {
  background: var(--bg-tertiary);
  border-radius: var(--radius-md);
  padding: 1rem;
  border: 1px solid var(--border-color);
}

.additional-info-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.additional-info-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.additional-info-icon {
  color: var(--download-secondary-color);
  font-size: 0.875rem;
  width: 16px;
  text-align: center;
}

.additional-info-text {
  color: var(--text-secondary);
  font-size: 0.875rem;
}

/* Secondary Actions */
.download-secondary-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

/* Footer */
.download-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.875rem;
}

.download-footer-info,
.download-stats {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.footer-icon,
.stats-icon {
  color: var(--download-primary-color);
  font-size: 0.75rem;
}

.footer-text,
.stats-text {
  color: var(--text-muted);
}

/* Responsive Design */
@media (max-width: 768px) {
  .download-actions {
    width: 100%;
  }

  .download-btn {
    flex: 1;
    justify-content: center;
  }

  .file-info-grid {
    grid-template-columns: 1fr;
  }

  .download-footer {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .download-secondary-actions {
    flex-direction: column;
  }

  .download-btn--secondary {
    width: 100%;
    justify-content: center;
  }
}
</style>