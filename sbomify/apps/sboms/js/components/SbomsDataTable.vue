<template>
  <div class="data-table">
    <table class="table dashboard-table">
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">Artifact Type</th>
          <th scope="col">Format</th>
          <th scope="col">Version</th>
          <th scope="col">NTIA Compliant</th>
          <th scope="col">Created</th>
          <th scope="col">Releases</th>
          <th v-if="showVulnerabilities" scope="col">Vulnerabilities</th>
          <th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="itemData in sbomsData" :key="itemData.sbom.id">
          <td data-label="Name">
            <a :href="getSbomDetailUrl(itemData.sbom.id)" title="Details" class="icon-link">
              {{ itemData.sbom.name }}
            </a>
          </td>
          <td data-label="Artifact Type">SBOM</td>
          <td data-label="Format">
            <span class="badge bg-success-subtle text-success">
              {{ getFormatDisplay(itemData.sbom.format) }} {{ itemData.sbom.format_version }}
            </span>
          </td>
          <td data-label="Version" :title="itemData.sbom.version">
            {{ truncateText(itemData.sbom.version, 20) }}
          </td>
          <td data-label="NTIA Compliant">
            <NTIAComplianceBadge
              :status="(itemData.sbom.ntia_compliance_status as NtiaStatus) || 'unknown'"
              :complianceDetails="itemData.sbom.ntia_compliance_details || {}"
              :teamBillingPlan="teamBillingPlan"
              :teamKey="teamKey"
            />
          </td>
          <td data-label="Created">{{ utils.formatDate(itemData.sbom.created_at) }}</td>
          <td data-label="Releases">
            <ReleaseList
              :releases="itemData.releases"
              :item-id="itemData.sbom.id"
              :is-public-view="isPublicView"
              :view-all-url="getSbomReleasesUrl(itemData.sbom.id)"
            />
          </td>
          <td v-if="showVulnerabilities" data-label="Vulnerabilities">
            <div v-if="itemData.vulnerability_counts" class="vuln-counts">
              <a :href="`/sbom/${itemData.sbom.id}/vulnerabilities`" class="vuln-counts-link">
                <span class="vuln-badge vuln-badge--critical" :title="`${itemData.vulnerability_counts.critical} Critical`">
                  {{ itemData.vulnerability_counts.critical }}
                </span>
                <span class="vuln-badge vuln-badge--high" :title="`${itemData.vulnerability_counts.high} High`">
                  {{ itemData.vulnerability_counts.high }}
                </span>
                <span class="vuln-badge vuln-badge--medium" :title="`${itemData.vulnerability_counts.medium} Medium`">
                  {{ itemData.vulnerability_counts.medium }}
                </span>
                <span class="vuln-badge vuln-badge--low" :title="`${itemData.vulnerability_counts.low} Low`">
                  {{ itemData.vulnerability_counts.low }}
                </span>
              </a>
            </div>
            <span v-else class="text-muted small">No scan</span>
          </td>
          <td data-label="Actions">
            <div class="d-flex gap-2">
              <a :href="getSbomDownloadUrl(itemData.sbom.id)" title="Download" class="btn btn-outline-primary btn-sm action-btn">
                <i class="fas fa-download"></i>
              </a>
              <!-- Manual scan button removed - vulnerability scans now run weekly automatically -->
              <button
                v-if="showDeleteButton"
                class="btn btn-sm btn-outline-danger action-btn"
                title="Delete SBOM"
                :disabled="isDeleting === itemData.sbom.id"
                @click="$emit('delete', itemData.sbom)"
              >
                <i v-if="isDeleting === itemData.sbom.id" class="fas fa-spinner fa-spin"></i>
                <i v-else class="fas fa-trash"></i>
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import NTIAComplianceBadge from './NTIAComplianceBadge.vue'
import ReleaseList from '../../../core/js/components/ReleaseList.vue'
import { useCommonUtils } from '../../../core/js/composables/useCommonUtils'
import { useUrlGeneration } from '../../../core/js/composables/useUrlGeneration'

type NtiaStatus = 'compliant' | 'partial' | 'non_compliant' | 'unknown'

interface NtiaComplianceError {
  field: string
  message: string
  suggestion?: string
}

interface NtiaComplianceCheck {
  element?: string
  title: string
  status?: string
  message: string
  suggestion?: string | null
  affected?: string[]
}

interface NtiaComplianceSection {
  name?: string
  title: string
  summary: string
  status?: string
  metrics?: {
    total?: number
    pass?: number
    warning?: number
    fail?: number
    unknown?: number
  }
  checks?: NtiaComplianceCheck[]
}

interface NtiaComplianceSummary {
  errors?: number
  warnings?: number
  status?: string
  score?: number | null
  checks?: {
    total?: number
    pass?: number
    warning?: number
    fail?: number
    unknown?: number
  }
  sections?: Record<
    string,
    {
      status?: string
      metrics?: {
        total?: number
        pass?: number
        warning?: number
        fail?: number
        unknown?: number
      }
      title?: string
      summary?: string
    }
  >
}

interface NtiaComplianceDetails {
  is_compliant?: boolean
  status?: string
  error_count?: number
  warning_count?: number
  errors?: NtiaComplianceError[]
  warnings?: NtiaComplianceCheck[]
  sections?: NtiaComplianceSection[]
  summary?: NtiaComplianceSummary
  checked_at?: string | null
  format?: string
}

interface Sbom {
  id: string
  name: string
  format: string
  format_version: string
  version: string
  created_at: string
  ntia_compliance_status?: NtiaStatus
  ntia_compliance_details?: NtiaComplianceDetails | null
}

interface Release {
  id: string
  name: string
  product_name: string
  is_latest: boolean
  is_prerelease: boolean
  is_public: boolean
  product_id?: string
  product?: {
    id: string
    name: string
  }
}

interface VulnerabilityCounts {
  critical: number
  high: number
  medium: number
  low: number
  total: number
}

interface SbomData {
  sbom: Sbom
  has_vulnerabilities_report: boolean
  releases: Release[]
  vulnerability_counts?: VulnerabilityCounts | null
}

const props = defineProps<{
  sbomsData: SbomData[]
  componentId?: string
  isPublicView?: boolean
  showVulnerabilities?: boolean
  showDeleteButton?: boolean
  isDeleting?: string | null
  teamBillingPlan?: string
  teamKey?: string
}>()

// Use composables
const utils = useCommonUtils()
const urlGen = useUrlGeneration(props.isPublicView)

// defineEmits removed - using $emit directly in template

// State for vulnerability scanning
// isScanning state removed - manual scanning no longer needed

const getSbomDetailUrl = (sbomId: string): string => {
  return urlGen.getSbomDetailUrl(sbomId, props.componentId)
}

const getSbomDownloadUrl = (sbomId: string): string => {
  return urlGen.getSbomDownloadUrl(sbomId)
}



const getSbomReleasesUrl = (sbomId: string): string => {
  return urlGen.getSbomReleasesUrl(sbomId)
}

const getFormatDisplay = (format: string): string => {
  switch (format.toLowerCase()) {
    case 'cyclonedx':
      return 'CycloneDX'
    case 'spdx':
      return 'SPDX'
    default:
      return format.toUpperCase()
  }
}

const truncateText = (text: string | null | undefined, maxLength: number): string => {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

// getCsrfToken function removed - manual scanning no longer needed

// Manual scan functionality removed - vulnerability scans now run weekly automatically
</script>

<style scoped>
.data-table {
  overflow-x: auto;
}

.table {
  margin-bottom: 0;
}

.icon-link {
  text-decoration: none;
}

.icon-link:hover {
  text-decoration: underline;
}

.btn.disabled {
  opacity: 0.6;
  pointer-events: none;
}

/* Action Button Styling */
.action-btn {
  border-radius: 0.5rem;
  font-weight: 500;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2.5rem;
  height: 2.25rem;
  border-width: 1.5px;
  font-size: 0.875rem;
}

.action-btn i {
  font-size: 0.875rem;
}

.action-btn.btn-outline-primary {
  background-color: #fff;
  border-color: #0d6efd;
  color: #0d6efd;
  box-shadow: 0 1px 2px rgba(13, 110, 253, 0.15);
}

.action-btn.btn-outline-primary:hover {
  background: linear-gradient(135deg, #0d6efd, #0b5ed7);
  border-color: #0d6efd;
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(13, 110, 253, 0.3);
}

.action-btn.btn-outline-danger {
  background-color: #fff;
  border-color: #dc3545;
  color: #dc3545;
  box-shadow: 0 1px 2px rgba(220, 53, 69, 0.15);
}

.action-btn.btn-outline-danger:hover:not(:disabled) {
  background: linear-gradient(135deg, #dc3545, #c82333);
  border-color: #dc3545;
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(220, 53, 69, 0.3);
}

.action-btn.btn-outline-warning {
  background-color: #fff;
  border-color: #ffc107;
  color: #ffc107;
  box-shadow: 0 1px 2px rgba(255, 193, 7, 0.15);
}

.action-btn.btn-outline-warning:hover:not(:disabled) {
  background: linear-gradient(135deg, #ffc107, #e0a800);
  border-color: #ffc107;
  color: #000;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(255, 193, 7, 0.3);
}

.action-btn.btn-outline-success:hover:not(:disabled) {
  background: linear-gradient(135deg, #10b981, #047857);
  border-color: #10b981;
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3);
}

.action-btn:disabled {
  opacity: 0.6;
  pointer-events: none;
  transform: none;
}

/* Vulnerability Count Badges */
.vuln-counts {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.vuln-counts-link {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  text-decoration: none;
}

.vuln-counts-link:hover .vuln-badge {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
}

.vuln-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.5rem;
  height: 1.5rem;
  padding: 0 0.35rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  font-weight: 600;
  transition: all 0.15s ease;
}

.vuln-badge--critical {
  background: rgba(220, 38, 38, 0.15);
  color: #dc2626;
  border: 1px solid rgba(220, 38, 38, 0.3);
}

.vuln-badge--high {
  background: rgba(234, 88, 12, 0.15);
  color: #ea580c;
  border: 1px solid rgba(234, 88, 12, 0.3);
}

.vuln-badge--medium {
  background: rgba(202, 138, 4, 0.15);
  color: #ca8a04;
  border: 1px solid rgba(202, 138, 4, 0.3);
}

.vuln-badge--low {
  background: rgba(37, 99, 235, 0.15);
  color: #2563eb;
  border: 1px solid rgba(37, 99, 235, 0.3);
}

/* Responsive badge handling */
@media (max-width: 768px) {
  .release-tags {
    flex-direction: column;
    align-items: flex-start;
  }
  
  .vuln-counts {
    flex-wrap: wrap;
  }
}
</style>
