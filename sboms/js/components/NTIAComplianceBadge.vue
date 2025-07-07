<template>
  <div class="ntia-compliance-badge">
    <!-- Compliant Badge -->
    <div
      v-if="status === 'compliant'"
      class="badge bg-success-subtle text-success d-flex align-items-center gap-1 compliant-badge"
      data-bs-toggle="tooltip"
      data-bs-placement="top"
      :title="getTooltipText()"
    >
      <i class="fas fa-award"></i>
      <span>Compliant</span>
    </div>

    <!-- Non-Compliant Badge (only show on private view) -->
    <div
      v-else-if="status === 'non_compliant' && !isPublicView"
      class="badge bg-warning-subtle text-warning d-flex align-items-center gap-1"
      data-bs-toggle="tooltip"
      data-bs-placement="top"
      :title="getTooltipText()"
      style="cursor: pointer;"
      @click="showDetailsModal = true"
    >
      <i class="fas fa-exclamation-triangle"></i>
      <span>Not Compliant</span>
    </div>

    <!-- Unknown Badge (only show on private view) -->
    <div
      v-else-if="status === 'unknown' && !isPublicView"
      class="badge bg-info-subtle text-info d-flex align-items-center gap-1 ntia-checking"
      data-bs-toggle="tooltip"
      data-bs-placement="top"
      :title="getTooltipText()"
    >
      <i class="fas fa-clock fa-pulse"></i>
      <span>Checking...</span>
    </div>

    <!-- Details Modal for Non-Compliant Status -->
    <div
      v-if="showDetailsModal"
      class="modal fade show"
      style="display: block; background-color: rgba(0,0,0,0.5);"
      tabindex="-1"
      @click.self="showDetailsModal = false"
    >
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="fas fa-shield-exclamation text-warning me-2"></i>
              NTIA Compliance Issues
            </h5>
            <button
              type="button"
              class="btn-close"
              @click="showDetailsModal = false"
            ></button>
          </div>
          <div class="modal-body">
            <div class="alert alert-warning d-flex align-items-start">
              <i class="fas fa-exclamation-triangle me-3 mt-1 flex-shrink-0"></i>
              <div>
                <strong>This SBOM does not meet NTIA minimum elements requirements.</strong>
                <br>
                Please review the issues below and consider using our GitHub Actions module to generate compliant SBOMs.
              </div>
            </div>

            <div v-if="complianceErrors.length > 0" class="mb-4">
              <div class="section-header mb-3">
                <h6 class="section-title">
                  <i class="fas fa-exclamation-circle me-2"></i>
                  Issues Found ({{ complianceErrors.length }})
                </h6>
              </div>
              <div class="ntia-issues-list">
                <div
                  v-for="(error, index) in complianceErrors"
                  :key="index"
                  class="ntia-issue-item mb-3"
                >
                  <div class="ntia-issue-header" @click="toggleIssue(index)">
                    <div class="d-flex align-items-center">
                      <i class="fas fa-exclamation-triangle text-warning me-2"></i>
                      <span class="ntia-issue-field">{{ error.field }}:</span>
                      <span class="ntia-issue-message ms-2">{{ error.message }}</span>
                      <i
                        class="fas fa-chevron-down ms-auto transition-transform"
                        :class="{ 'rotate-180': expandedIssues.includes(index) }"
                      ></i>
                    </div>
                  </div>
                  <div
                    v-if="expandedIssues.includes(index)"
                    class="ntia-issue-body"
                  >
                    <div class="ntia-suggestion">
                      <i class="fas fa-lightbulb text-info me-2"></i>
                      <strong>Suggestion:</strong> {{ error.suggestion }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="alert alert-info">
              <div class="section-header-info mb-3">
                <h6 class="section-title-info">
                  <i class="fas fa-lightbulb me-2"></i>
                  How to Fix This
                </h6>
              </div>
                <ul class="mb-0 fix-suggestions">
                  <li class="mb-2">
                    <strong>Use our <a href="https://github.com/sbomify/github-action" target="_blank" rel="noopener" class="text-decoration-none">GitHub Actions module</a></strong> for automated SBOM generation
                  </li>
                  <li class="mb-2">
                    <strong>Ensure your SBOM includes all 7 NTIA minimum elements:</strong>
                    <ul class="mt-2 ntia-elements-list">
                      <li>Supplier name</li>
                      <li>Component name</li>
                      <li>Version of the component</li>
                      <li>Other unique identifiers (PURL, CPE, etc.)</li>
                      <li>Dependency relationships</li>
                      <li>Author of SBOM data</li>
                      <li>Timestamp</li>
                    </ul>
                  </li>
                  <li>
                    <strong>Validate your SBOM</strong> before uploading using SBOM validation tools
                  </li>
                                  </ul>
              </div>
          </div>
          <div class="modal-footer">
            <button
              type="button"
              class="btn btn-secondary"
              @click="showDetailsModal = false"
            >
              Close
            </button>
            <a
              href="https://github.com/sbomify/github-action"
              target="_blank"
              rel="noopener"
              class="btn btn-primary"
            >
              <i class="fab fa-github me-2"></i>
              View GitHub Action
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

interface ComplianceError {
  field: string
  message: string
  suggestion: string
}

interface Props {
  status: 'compliant' | 'non_compliant' | 'unknown'
  complianceDetails?: {
    errors?: ComplianceError[]
    checked_at?: string
    error_count?: number
  }
  isPublicView?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  complianceDetails: () => ({}),
  isPublicView: false
})

const showDetailsModal = ref(false)
const expandedIssues = ref<number[]>([])

const complianceErrors = computed((): ComplianceError[] => {
  return props.complianceDetails?.errors || []
})

const toggleIssue = (index: number): void => {
  const currentIndex = expandedIssues.value.indexOf(index)
  if (currentIndex > -1) {
    expandedIssues.value.splice(currentIndex, 1)
  } else {
    expandedIssues.value.push(index)
  }
}

const getTooltipText = (): string => {
  switch (props.status) {
    case 'compliant':
      return 'This SBOM meets all NTIA minimum elements requirements'
    case 'non_compliant':
      const errorCount = props.complianceDetails?.error_count || complianceErrors.value.length
      return `This SBOM has ${errorCount} NTIA compliance issue${errorCount !== 1 ? 's' : ''}. Click for details.`
    case 'unknown':
      return 'NTIA compliance check is being performed in the background. This usually takes a few seconds to complete.'
    default:
      return 'NTIA compliance status unknown'
  }
}

// Initialize Bootstrap tooltips when component mounts
onMounted(() => {
  // Initialize tooltips (assuming Bootstrap 5 is available)
  const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]')
  if (typeof window !== 'undefined' && window.bootstrap?.Tooltip) {
    Array.from(tooltipTriggerList).forEach(tooltipTriggerEl => {
      new window.bootstrap!.Tooltip(tooltipTriggerEl)
    })
  }
})

// Clean up tooltips when component unmounts
onUnmounted(() => {
  const tooltips = document.querySelectorAll('.tooltip')
  tooltips.forEach(tooltip => tooltip.remove())
})
</script>

<style scoped>
.ntia-compliance-badge .badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.375rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid;
}

.ntia-compliance-badge .badge.bg-success-subtle {
  border-color: var(--bs-success-border-subtle);
}

.ntia-compliance-badge .badge.bg-warning-subtle {
  border-color: var(--bs-warning-border-subtle);
}

.ntia-compliance-badge .badge.bg-secondary-subtle {
  border-color: var(--bs-secondary-border-subtle);
}

.ntia-compliance-badge .badge.bg-info-subtle {
  border-color: var(--bs-info-border-subtle);
}

.ntia-compliance-badge .badge i {
  font-size: 0.875rem;
}

.ntia-compliance-badge .compliant-badge {
  background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%) !important;
  border-color: #198754 !important;
  position: relative;
  overflow: visible;
}

.ntia-compliance-badge .compliant-badge i {
  color: #ffc107;
  font-size: 1rem;
  filter: drop-shadow(0 1px 2px rgba(255, 193, 7, 0.3));
}

.ntia-compliance-badge .compliant-badge:before {
  content: "";
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.2) 0%, rgba(25, 135, 84, 0.2) 100%);
  border-radius: 0.5rem;
  z-index: -1;
}

/* NTIA Issues List Styling */
.ntia-issues-list {
  background-color: #f8f9fa;
  border-radius: 0.75rem;
  padding: 1rem;
  border: 1px solid #e9ecef;
}

.ntia-issue-item {
  background: linear-gradient(135deg, #fff 0%, #fafafa 100%);
  border: 1px solid #e9ecef;
  border-radius: 0.75rem;
  overflow: hidden;
  transition: all 0.2s ease-in-out;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.ntia-issue-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  border-color: #ffc107;
}

.ntia-issue-header {
  padding: 1.25rem;
  cursor: pointer;
  user-select: none;
  background: linear-gradient(135deg, #fff8e1 0%, #fff3cd 100%);
  border-bottom: 1px solid #ffeaa7;
  transition: all 0.2s ease-in-out;
}

.ntia-issue-header:hover {
  background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
}

.ntia-issue-field {
  font-weight: 700;
  color: #d63384;
  font-size: 0.95rem;
  text-transform: capitalize;
}

.ntia-issue-message {
  color: #495057;
  flex: 1;
  font-size: 0.9rem;
  line-height: 1.4;
}

.ntia-issue-body {
  padding: 1.25rem;
  background-color: #fff;
}

.ntia-suggestion {
  background: linear-gradient(135deg, #e3f2fd 0%, #f0f8ff 100%);
  padding: 1rem;
  border-radius: 0.5rem;
  border-left: 4px solid #2196f3;
  font-size: 0.9rem;
  line-height: 1.5;
  box-shadow: 0 2px 4px rgba(33, 150, 243, 0.1);
}

/* Section headers */
.section-header {
  background: linear-gradient(135deg, #fff 0%, #f8f9fa 100%);
  padding: 1rem 1.25rem;
  border-radius: 0.75rem;
  border: 1px solid #e9ecef;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.section-title {
  margin: 0;
  font-weight: 700;
  color: #dc3545;
  font-size: 1rem;
  display: flex;
  align-items: center;
}

.section-title i {
  color: #ffc107;
}

.section-header-info {
  background: linear-gradient(135deg, #e3f2fd 0%, #f0f8ff 100%);
  padding: 1.25rem 1.5rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(13, 202, 240, 0.3);
  box-shadow: 0 2px 4px rgba(13, 202, 240, 0.1);
}

.section-title-info {
  margin: 0;
  font-weight: 700;
  color: #0c5460;
  font-size: 1rem;
  display: flex;
  align-items: center;
}

.section-title-info i {
  color: #ffc107;
}

/* Alert styling improvements */
.alert {
  border: none !important;
  border-radius: 0.75rem !important;
  font-size: 0.95rem;
}

.alert-warning {
  background: linear-gradient(135deg, #fff8e1 0%, #fff3cd 100%) !important;
  color: #856404 !important;
  box-shadow: 0 2px 4px rgba(255, 193, 7, 0.2);
  padding: 1.5rem !important;
  line-height: 1.6;
}

.alert-info {
  background: linear-gradient(135deg, #e3f2fd 0%, #f0f8ff 100%) !important;
  color: #0c5460 !important;
  box-shadow: 0 2px 4px rgba(13, 202, 240, 0.2);
  padding: 1.5rem !important;
  line-height: 1.6;
}

/* Fix suggestions styling */
.fix-suggestions {
  margin-bottom: 0;
  padding-left: 0;
  list-style: none;
}

.fix-suggestions > li {
  margin-bottom: 1.25rem;
  font-size: 0.95rem;
  line-height: 1.6;
  position: relative;
  padding-left: 2rem;
}

.fix-suggestions > li:last-child {
  margin-bottom: 0;
}

.fix-suggestions > li:before {
  content: "•";
  position: absolute;
  left: 0;
  top: 0;
  color: #0d6efd;
  font-weight: bold;
  font-size: 1.2rem;
  width: 1.5rem;
  text-align: center;
  line-height: 1.6;
  height: 1.6rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fix-suggestions a {
  color: #0d6efd;
  font-weight: 600;
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: border-color 0.2s ease;
}

.fix-suggestions a:hover {
  border-bottom-color: #0d6efd;
}

.ntia-elements-list {
  margin-top: 0.75rem;
  margin-bottom: 0;
  background-color: rgba(255, 255, 255, 0.5);
  padding: 1.25rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(13, 202, 240, 0.2);
  list-style: none;
}

.ntia-elements-list li {
  color: #495057;
  font-size: 0.95rem;
  margin-bottom: 0.5rem;
  position: relative;
  padding-left: 1.75rem;
  line-height: 1.5;
}

.ntia-elements-list li:last-child {
  margin-bottom: 0;
}

.ntia-elements-list li:before {
  content: "✓";
  position: absolute;
  left: 0;
  top: 0.1rem;
  color: #198754;
  font-weight: bold;
  font-size: 1rem;
  width: 1.25rem;
  text-align: center;
}

/* Transition animations */
.transition-transform {
  transition: transform 0.2s ease-in-out;
}

.rotate-180 {
  transform: rotate(180deg);
}

/* Modal styling improvements */
.modal {
  z-index: 1060;
}

.modal-backdrop {
  z-index: 1055;
}

.modal-lg {
  max-width: 850px;
}

.modal-content {
  border: none;
  border-radius: 1rem;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}

.modal-header {
  background: linear-gradient(135deg, #fff 0%, #f8f9fa 100%);
  border-bottom: 1px solid #e9ecef;
  border-radius: 1rem 1rem 0 0;
  padding: 1.5rem;
}

.modal-title {
  font-weight: 700;
  font-size: 1.25rem;
  color: #495057;
}

.modal-body {
  padding: 2rem;
  background-color: #fff;
}

.modal-footer {
  background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
  border-top: 1px solid #e9ecef;
  border-radius: 0 0 1rem 1rem;
  padding: 1.5rem;
}

.btn-primary {
  background: linear-gradient(135deg, #0d6efd 0%, #0b5ed7 100%);
  border: none;
  border-radius: 0.5rem;
  padding: 0.75rem 1.5rem;
  font-weight: 600;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(13, 110, 253, 0.3);
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(13, 110, 253, 0.4);
}

.btn-secondary {
  background: linear-gradient(135deg, #6c757d 0%, #5a6268 100%);
  border: none;
  border-radius: 0.5rem;
  padding: 0.75rem 1.5rem;
  font-weight: 600;
  transition: all 0.2s ease;
}

/* Badge checking animation */
.ntia-checking {
  opacity: 0.9;
  animation: subtle-pulse 2s infinite ease-in-out;
}

@keyframes subtle-pulse {
  0%, 100% {
    opacity: 0.9;
  }
  50% {
    opacity: 0.7;
  }
}
</style>