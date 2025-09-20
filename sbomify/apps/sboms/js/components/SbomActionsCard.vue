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
          <h6 class="action-title">Vulnerability Analysis</h6>
          <p class="action-description">View vulnerability scan results, security insights, and trends from automatic weekly scans</p>
          <a :href="vulnerabilitiesUrl" class="btn btn-warning btn-action">
            <i class="fas fa-shield-alt me-2"></i>
            View Vulnerability Report
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

// ScanResult interface removed - manual scanning no longer needed

const props = defineProps<Props>()

// Computed URLs
const downloadUrl = computed(() => `/api/v1/sboms/${props.sbomId}/download`)
const vulnerabilitiesUrl = computed(() => `/sbom/${props.sbomId}/vulnerabilities`)



// Manual scan functionality removed - vulnerability scans now run weekly automatically
</script>

<style scoped>
.actions-grid {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

@media (min-width: 768px) {
  .actions-grid {
    flex-direction: row;
    gap: 1rem;
  }
}

@media (max-width: 767px) {
  .action-item {
    padding: 1.25rem;
  }

  .action-description {
    max-width: none;
  }
}

.action-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 1rem;
  padding: 1.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  transition: all 0.2s ease;
  flex: 1;
  min-width: 0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.action-item:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.action-icon {
  width: 4rem;
  height: 4rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  color: white;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.download-icon {
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
}

.vulnerability-icon {
  background: linear-gradient(135deg, #f59e0b, #d97706);
}

.action-content {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}

.action-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #1f2937;
  margin: 0;
  text-align: center;
}

.action-description {
  font-size: 0.875rem;
  color: #6b7280;
  margin: 0;
  line-height: 1.5;
  text-align: center;
  max-width: 250px;
}

.btn-action {
  padding: 0.75rem 1.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  border-radius: 8px;
  border: none;
  transition: all 0.2s ease;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  min-width: 140px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.btn-action:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  text-decoration: none;
}

.btn-action:active {
  transform: translateY(0);
}

.btn-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.btn-primary {
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  color: white;
}

.btn-warning {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
}

.btn-success {
  background: linear-gradient(135deg, #10b981, #047857);
  color: white;
}

.btn-secondary {
  background: linear-gradient(135deg, #6b7280, #4b5563);
  color: white;
}

.form-check {
  margin-top: 0.5rem;
}

.form-check-label {
  font-size: 0.75rem;
  cursor: pointer;
}

.alert {
  border-radius: 6px;
  border: none;
}

.btn-close {
  font-size: 0.75rem;
}

@media (max-width: 1199px) {
  .actions-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 767px) {
  .actions-grid {
    grid-template-columns: 1fr;
  }

  .action-item {
    padding: 1rem;
    gap: 0.75rem;
  }

  .action-icon {
    width: 2.5rem;
    height: 2.5rem;
    font-size: 1rem;
  }
}
</style>