<template>
  <div class="public-page-layout" :style="themeStyles">
    <!-- Main Content Area -->
    <div class="content-wrapper">
      <div class="content-background"></div>
      <div class="content-container">
        <!-- Breadcrumb -->
        <div id="breadcrumb-slot" class="breadcrumb-container"></div>

        <!-- Page Header -->
        <div class="public-page-header">
          <div class="page-header-content">
            <h1 class="page-title">
              <i v-if="titleIcon" :class="titleIcon" class="title-icon"></i>
              {{ title }}
            </h1>
            <div v-if="subtitle || hasSubtitleSlot" class="page-subtitle">
              <div v-if="hasSubtitleSlot" id="subtitle-slot"></div>
              <span v-else class="subtitle-text">{{ subtitle }}</span>
            </div>
          </div>

          <!-- Quick Actions -->
          <div v-if="quickActions && quickActions.length > 0" class="page-header-actions">
                    <button
          v-for="action in quickActions"
          :key="action.id"
          :class="['quick-action-btn', `quick-action-btn--${action.variant || 'default'}`]"
          :disabled="action.disabled"
          @click="handleAction(action)"
        >
              <i v-if="action.icon" :class="action.icon" class="action-icon"></i>
              <span>{{ action.text }}</span>
            </button>
          </div>
        </div>

        <!-- Main Content -->
        <div class="public-main-content">
          <!-- Page Content Based on Type -->
          <div class="content-section">
            <!-- Product Page Content -->
            <div v-if="pageType === 'product'" class="product-content">
              <div class="product-identifiers-section">
                <ProductIdentifiers
                  :productId="itemId"
                  :hasCrudPermissions="false"
                  billingPlan="business"
                />
              </div>

              <div class="product-links-section">
                <ProductLinks
                  :productId="itemId"
                  :hasCrudPermissions="false"
                />
              </div>

              <div class="product-projects-section">
                <PublicProductProjects
                  :productId="itemId"
                  :brandColor="brandColor"
                  :accentColor="accentColor"
                />
              </div>

              <!-- Download Card for Product -->
              <div v-if="hasDownloadContent" class="download-section">
                <PublicDownloadCard
                  :title="downloadTitle || 'Download Product SBOM'"
                  :description="downloadDescription"
                  :downloadUrl="downloadUrl"
                  :downloadText="downloadButtonText || 'Download SBOM'"
                  :downloadIcon="downloadIcon || 'fas fa-download'"
                  :fileInfo="downloadFileInfo"
                  :additionalInfo="downloadAdditionalInfo"
                  :downloadCount="downloadCount"
                  @download="handleDownload"
                />
              </div>
            </div>

            <!-- Project Page Content -->
            <div v-else-if="pageType === 'project'" class="project-content">
              <PublicProjectComponents
                :projectId="itemId"
                :brandColor="brandColor"
                :accentColor="accentColor"
              />

              <!-- Download Card for Project -->
              <div v-if="hasDownloadContent" class="download-section">
                <PublicDownloadCard
                  :title="downloadTitle || 'Download Project SBOM'"
                  :description="downloadDescription"
                  :downloadUrl="downloadUrl"
                  :downloadText="downloadButtonText || 'Download SBOM'"
                  :downloadIcon="downloadIcon || 'fas fa-download'"
                  :fileInfo="downloadFileInfo"
                  :additionalInfo="downloadAdditionalInfo"
                  :downloadCount="downloadCount"
                  @download="handleDownload"
                />
              </div>
            </div>

            <!-- Component Page Content -->
            <div v-else-if="pageType === 'component'" class="component-content">
              <!-- SBOM Component -->
              <div v-if="componentType === 'sbom'">
                <PublicCard
                  title="SBOMs"
                  subtitle="Software Bill of Materials for this component"
                  icon="fas fa-file-code"
                  variant="default"
                  size="lg"
                >
                  <SbomsTable
                    sboms-data-element-id="sboms-data"
                    :component-id="itemId"
                    :has-crud-permissions="false"
                    :is-public-view="true"
                  />
                </PublicCard>
              </div>

              <!-- Document Component -->
              <div v-else-if="componentType === 'document'">
                <PublicCard
                  title="Documents"
                  subtitle="Documents for this component"
                  icon="fas fa-file-alt"
                  variant="default"
                  size="lg"
                >
                  <DocumentsTable
                    documents-data-element-id="documents-data"
                    :component-id="itemId"
                    :has-crud-permissions="false"
                    :is-public-view="true"
                  />
                </PublicCard>
              </div>

              <!-- Other Component Types -->
              <div v-else>
                <PublicCard
                  title="Component Details"
                  :subtitle="`Component type: ${componentDisplayType || 'Unknown'}`"
                  icon="fas fa-cube"
                  variant="info"
                  size="lg"
                >
                  <div class="empty-state">
                    <i class="fas fa-cube empty-icon"></i>
                    <h3 class="empty-title">{{ componentDisplayType || 'Component' }}</h3>
                    <p class="empty-description">This component is available but doesn't have additional details to display.</p>
                  </div>
                </PublicCard>
              </div>
            </div>

            <!-- Component Detailed Page Content -->
            <div v-else-if="pageType === 'component-detailed'" class="component-detailed-content">
              <div v-if="hasDownloadContent" class="component-download-section">
                <PublicDownloadCard
                  :title="downloadTitle || 'Download Component'"
                  :description="downloadDescription"
                  :downloadUrl="downloadUrl"
                  :downloadText="downloadButtonText || 'Download'"
                  :downloadIcon="downloadIcon || 'fas fa-download'"
                  :fileInfo="downloadFileInfo"
                  :additionalInfo="downloadAdditionalInfo"
                  @download="handleDownload"
                />
              </div>
            </div>

            <!-- Custom Content Slot -->
            <div v-if="$slots.default" class="custom-content">
              <slot></slot>
            </div>
          </div>



          <!-- Additional Information -->
          <div v-if="additionalSections && additionalSections.length > 0" class="additional-sections">
            <PublicCard
              v-for="section in additionalSections"
              :key="section.id"
              :title="section.title"
              :subtitle="section.subtitle"
              :icon="section.icon"
              :variant="section.variant || 'default'"
              size="lg"
                          >
                <div>{{ section.content }}</div>
              </PublicCard>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PublicProductProjects from './PublicProductProjects.vue'
import PublicProjectComponents from './PublicProjectComponents.vue'
import PublicDownloadCard from './PublicDownloadCard.vue'
import PublicCard from './PublicCard.vue'
import ProductIdentifiers from './ProductIdentifiers.vue'
import ProductLinks from './ProductLinks.vue'
import DocumentsTable from '@/documents/js/components/DocumentsTable.vue'
import SbomsTable from '@/sboms/js/components/SbomsTable.vue'

interface QuickAction {
  id: string
  text: string
  icon?: string
  variant?: 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error'
  disabled?: boolean
  action: () => void
}

interface FileInfo {
  size?: number
  type?: string
  lastModified?: string
}

interface AdditionalInfo {
  icon?: string
  text: string
}

interface AdditionalSection {
  id: string
  title: string
  subtitle?: string
  icon?: string
  variant?: 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'
  content: string
}

interface Props {
  title?: string
  subtitle?: string
  titleIcon?: string
  brandImage?: string
  brandName?: string
  brandColor?: string
  accentColor?: string
  showBreadcrumb?: boolean
  pageType?: string
  itemId?: string
  componentType?: string
  componentDisplayType?: string
  downloadUrl?: string
  downloadTitle?: string
  downloadButtonText?: string
  downloadDescription?: string
  downloadIcon?: string
  downloadFileInfo?: FileInfo
  downloadAdditionalInfo?: AdditionalInfo[]
  downloadCount?: number
  quickActions?: QuickAction[]
  additionalSections?: AdditionalSection[]
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  subtitle: '',
  titleIcon: '',
  brandImage: '',
  brandName: '',
  brandColor: '#4f46e5',
  accentColor: '#7c8b9d',
  showBreadcrumb: true,
  pageType: '',
  itemId: '',
  componentType: '',
  componentDisplayType: '',
  downloadUrl: '',
  downloadTitle: '',
  downloadButtonText: '',
  downloadDescription: '',
  downloadIcon: '',
  downloadFileInfo: undefined,
  downloadAdditionalInfo: () => [],
  downloadCount: 0,
  quickActions: () => [],
  additionalSections: () => []
})

const hasSubtitleSlot = ref(false)

// Computed properties using props instead of DOM queries
const pageType = computed(() => props.pageType)
const itemId = computed(() => props.itemId)
const componentType = computed(() => props.componentType)
const componentDisplayType = computed(() => props.componentDisplayType)

// Computed property to check if there's downloadable content
const hasDownloadContent = computed(() => {
  return props.downloadUrl &&
         props.downloadUrl.trim() !== '' &&
         props.downloadUrl !== 'undefined' &&
         props.downloadUrl !== 'null'
})

onMounted(() => {
  // Use a more robust approach to ensure DOM is ready
  const processTemplates = () => {
    try {
      // Find and process subtitle content
      const subtitleTemplate = document.querySelector('template[data-slot="subtitle"]') as HTMLTemplateElement
      if (subtitleTemplate) {
        hasSubtitleSlot.value = true
        const subtitleSlot = document.querySelector('#subtitle-slot')
        if (subtitleSlot) {
          // Safely move DOM nodes instead of using innerHTML
          const fragment = subtitleTemplate.content.cloneNode(true)
          subtitleSlot.appendChild(fragment)
        }
        subtitleTemplate.remove()
      }

      // Find breadcrumbs rendered by Django and move them to the correct location
      const breadcrumbElement = document.querySelector('.public-breadcrumb')
      const breadcrumbSlot = document.querySelector('#breadcrumb-slot')

      if (breadcrumbElement && breadcrumbSlot) {
        // Move the breadcrumb from its current location to the slot within Vue component
        breadcrumbSlot.appendChild(breadcrumbElement)
        console.log('Breadcrumb moved successfully')
      } else {
        console.log('Breadcrumb elements not found:', {
          breadcrumbElement: !!breadcrumbElement,
          breadcrumbSlot: !!breadcrumbSlot
        })
      }
    } catch (error) {
      console.error('Error processing templates:', error)
    }
  }

  // Try immediate processing first
  processTemplates()

  // If elements weren't found, try again after a delay
  setTimeout(() => {
    processTemplates()
  }, 100)

  // Components are mounted by their respective main.ts files - no manual mounting needed
})

const themeStyles = computed(() => ({
  '--brand-color': props.brandColor,
  '--accent-color': props.accentColor,
  '--brand-color-dark': darkenColor(props.brandColor, 0.1),
  '--accent-color-dark': darkenColor(props.accentColor, 0.1),
  '--brand-color-light': lightenColor(props.brandColor, 0.1),
  '--accent-color-light': lightenColor(props.accentColor, 0.1),
}))

// Helper functions for color manipulation
function darkenColor(color: string, amount: number): string {
  const hex = color.replace('#', '')
  const r = parseInt(hex.substr(0, 2), 16)
  const g = parseInt(hex.substr(2, 2), 16)
  const b = parseInt(hex.substr(4, 2), 16)

  return `#${Math.max(0, Math.floor(r * (1 - amount))).toString(16).padStart(2, '0')}${Math.max(0, Math.floor(g * (1 - amount))).toString(16).padStart(2, '0')}${Math.max(0, Math.floor(b * (1 - amount))).toString(16).padStart(2, '0')}`
}

function lightenColor(color: string, amount: number): string {
  const hex = color.replace('#', '')
  const r = parseInt(hex.substr(0, 2), 16)
  const g = parseInt(hex.substr(2, 2), 16)
  const b = parseInt(hex.substr(4, 2), 16)

  return `#${Math.min(255, Math.floor(r + (255 - r) * amount)).toString(16).padStart(2, '0')}${Math.min(255, Math.floor(g + (255 - g) * amount)).toString(16).padStart(2, '0')}${Math.min(255, Math.floor(b + (255 - b) * amount)).toString(16).padStart(2, '0')}`
}

const emit = defineEmits<{
  download: [url: string]
  action: [action: QuickAction]
}>()

const handleDownload = (url: string) => {
  emit('download', url)
}

const handleAction = (action: QuickAction) => {
  if (action.disabled) return
  emit('action', action)
  action.action()
}
</script>

<style scoped>
.public-page-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  --brand-color: #4f46e5;
  --accent-color: #7c8b9d;
  --text-primary: #1a202c;
  --text-secondary: #64748b;
  --text-muted: #94a3b8;
  --bg-primary: #ffffff;
  --bg-secondary: #f8fafc;
  --border-color: #e2e8f0;
  --shadow-color: rgba(0, 0, 0, 0.1);
}

/* Content Wrapper */
.content-wrapper {
  flex: 1;
  position: relative;
  background-color: var(--bg-secondary);
  margin-top: 0;
}

.content-background {
  display: none;
}

.content-container {
  position: relative;
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
  z-index: 1;
}

/* Breadcrumb */
.breadcrumb-container {
  margin-bottom: 1.5rem;
}

/* Page Header */
.public-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 2rem;
  margin-bottom: 2rem;
  background: var(--bg-primary);
  border-radius: 1rem;
  padding: 2rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.02);
  border: 1px solid rgba(var(--brand-color-rgb), 0.1);
  border-left: 4px solid var(--brand-color);
}

.page-header-content {
  flex: 1;
}

.page-title {
  margin: 0 0 0.75rem 0;
  font-size: 2.25rem;
  font-weight: 700;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 1rem;
  line-height: 1.2;
}

.title-icon {
  color: var(--brand-color);
  font-size: 2rem;
  filter: drop-shadow(0 1px 2px rgba(var(--brand-color-rgb), 0.2));
}

.page-subtitle {
  color: var(--text-secondary);
  font-size: 1rem;
  line-height: 1.6;
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
}

.subtitle-text {
  display: block;
}

.page-header-actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.quick-action-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-weight: 500;
  text-decoration: none;
  transition: all 0.2s ease;
  cursor: pointer;
  font-size: 0.875rem;
  white-space: nowrap;
}

.quick-action-btn:hover:not(:disabled) {
  background: var(--bg-tertiary);
  border-color: var(--brand-color);
  transform: translateY(-1px);
}

.quick-action-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.quick-action-btn--primary {
  background: var(--brand-color);
  color: white;
  border-color: var(--brand-color);
}

.quick-action-btn--primary:hover:not(:disabled) {
  background: var(--brand-color-dark);
  border-color: var(--brand-color-dark);
}

.quick-action-btn--secondary {
  background: var(--accent-color);
  color: white;
  border-color: var(--accent-color);
}

.quick-action-btn--secondary:hover:not(:disabled) {
  background: var(--accent-color-dark);
  border-color: var(--accent-color-dark);
}

.action-icon {
  font-size: 0.875rem;
}

/* Main Content */
.public-main-content {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.download-section,
.content-section,
.additional-sections {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* Product and Project Content Sections */
.product-content,
.project-content {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.product-identifiers-section,
.product-projects-section,
.project-components-section {
  margin-bottom: 0;
}

.component-download-section {
  margin-bottom: 1.5rem;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 3rem 2rem;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 3rem;
  color: var(--text-muted);
  margin-bottom: 1rem;
}

.empty-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.5rem;
}

.empty-description {
  font-size: 1rem;
  line-height: 1.6;
  margin: 0;
}



/* Responsive Design */
@media (max-width: 1024px) {
  .page-title {
    font-size: 2rem;
  }

  .title-icon {
    font-size: 1.75rem;
  }
}

@media (max-width: 768px) {
  .public-page-header {
    flex-direction: column;
    align-items: stretch;
    gap: 1.5rem;
    padding: 1.5rem;
  }

  .page-header-actions {
    justify-content: flex-start;
  }

  .quick-action-btn {
    flex: 1;
    justify-content: center;
    min-width: 0;
  }

  .page-title {
    font-size: 1.75rem;
    gap: 0.75rem;
  }

  .title-icon {
    font-size: 1.5rem;
  }

  .page-subtitle {
    font-size: 0.875rem;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.75rem;
  }

  .empty-state {
    padding: 2rem 1rem;
  }

  .empty-icon {
    font-size: 2.5rem;
  }

  .empty-title {
    font-size: 1.25rem;
  }
}

@media (max-width: 480px) {
  .content-container {
    padding: 1.5rem 1rem;
  }

  .public-page-header {
    padding: 1rem;
    border-radius: 0.75rem;
  }

  .public-main-content {
    gap: 1.5rem;
  }

  .page-title {
    font-size: 1.5rem;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .quick-action-btn {
    width: 100%;
  }
}

/* High-DPI displays */
@media (-webkit-min-device-pixel-ratio: 2), (min-resolution: 192dpi) {
  /* High DPI styles for remaining elements if needed */
}
</style>