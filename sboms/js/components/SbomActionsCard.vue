<template>
  <StandardCard
    title="SBOM Actions"
    info-icon="fas fa-cogs"
    shadow="sm"
    :collapsible="true"
    :default-expanded="true"
    storage-key="sbom-actions"
  >
    <div class="actions-grid">
      <div class="action-item">
        <div class="action-icon download-icon">
          <i class="fas fa-download"></i>
        </div>
        <div class="action-content">
          <h6 class="action-title">Download SBOM</h6>
          <p class="action-description">Get the complete SBOM file in its original format</p>
          <a :href="downloadUrl" class="btn btn-primary btn-action">
            <i class="fas fa-download me-2"></i>
            Download File
          </a>
        </div>
      </div>

      <div class="action-item">
        <div class="action-icon vulnerability-icon">
          <i class="fas fa-shield-alt"></i>
        </div>
        <div class="action-content">
          <h6 class="action-title">Security Analysis</h6>
          <p class="action-description">View vulnerability analysis and security insights</p>
          <a :href="vulnerabilitiesUrl" class="btn btn-warning btn-action">
            <i class="fas fa-shield-alt me-2"></i>
            View Vulnerabilities
          </a>
        </div>
      </div>
    </div>
  </StandardCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StandardCard from '../../../core/js/components/StandardCard.vue'

interface Props {
  sbomId: string
}

const props = defineProps<Props>()

const downloadUrl = computed(() => `/sbom/download/${props.sbomId}`)
const vulnerabilitiesUrl = computed(() => `/sbom/${props.sbomId}/vulnerabilities`)
</script>

<style scoped>
.actions-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 2rem;
}

@media (min-width: 768px) {
  .actions-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.action-item {
  display: flex;
  gap: 1rem;
  padding: 1.5rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.75rem;
  background: #f8fafc;
  transition: all 0.2s ease;
}

.action-item:hover {
  border-color: #d1d5db;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
  transform: translateY(-1px);
}

.action-icon {
  width: 3rem;
  height: 3rem;
  border-radius: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  color: white;
  flex-shrink: 0;
}

.download-icon {
  background: linear-gradient(135deg, #059669, #047857);
}

.vulnerability-icon {
  background: linear-gradient(135deg, #f59e0b, #d97706);
}

.action-content {
  flex: 1;
}

.action-title {
  font-size: 1rem;
  font-weight: 600;
  color: #374151;
  margin: 0 0 0.5rem 0;
}

.action-description {
  font-size: 0.875rem;
  color: #6b7280;
  margin: 0 0 1rem 0;
  line-height: 1.5;
}

.btn-action {
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 500;
  border-radius: 0.5rem;
  transition: all 0.2s ease;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  border: none;
}

.btn-primary.btn-action {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
}

.btn-primary.btn-action:hover {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
  color: white;
  text-decoration: none;
}

.btn-warning.btn-action {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
  box-shadow: 0 2px 4px rgba(245, 158, 11, 0.3);
}

.btn-warning.btn-action:hover {
  background: linear-gradient(135deg, #d97706, #b45309);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.4);
  color: white;
  text-decoration: none;
}

@media (max-width: 767px) {
  .action-item {
    flex-direction: column;
    text-align: center;
    gap: 1rem;
  }

  .action-icon {
    align-self: center;
  }
}
</style>