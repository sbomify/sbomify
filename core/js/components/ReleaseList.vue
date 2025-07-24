<template>
  <div v-if="releases && releases.length > 0" class="releases-display">
    <div class="releases-list">
      <a
        v-for="release in displayedReleases"
        :key="release.id"
        :href="releaseDisplay.getReleaseUrl(release)"
        class="release-link"
        :title="`View ${release.product_name} - ${release.name}`"
      >
        <span class="product-name">{{ release.product_name }}</span>
        <span class="version-info">
          <span class="version-text" :class="{ 'is-latest': release.is_latest }">
            {{ release.is_latest ? 'latest' : release.name }}
          </span>
          <span v-if="release.is_prerelease" class="prerelease-label">pre</span>
        </span>
      </a>
    </div>

    <!-- Expansion controls -->
    <div v-if="releaseDisplay.shouldShowExpansion(releases)" class="release-expand">
      <button
        v-if="!releaseDisplay.shouldShowViewAll(releases)"
        class="expand-btn"
        @click="handleToggleExpansion"
      >
        {{ releaseDisplay.getExpansionButtonText(releases, expansionKey) }}
      </button>
      <div v-else class="release-actions">
        <button
          class="expand-btn"
          @click="handleToggleExpansion"
        >
          {{ releaseDisplay.getExpansionButtonText(releases, expansionKey) }}
        </button>
        <a
          v-if="viewAllUrl"
          :href="viewAllUrl"
          class="view-all-btn"
          title="View all releases"
        >
          View all {{ releases.length }} →
        </a>
      </div>
    </div>
  </div>
  <div v-else class="empty-releases">
    <span>No releases</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useReleaseDisplay, type Release } from '../composables/useReleaseDisplay'

interface Props {
  releases: Release[]
  itemId: string
  isPublicView?: boolean
  viewAllUrl?: string
}

const props = withDefaults(defineProps<Props>(), {
  isPublicView: false,
  viewAllUrl: ''
})

// Use the release display composable
const releaseDisplay = useReleaseDisplay(props.isPublicView)

// Generate expansion key
const expansionKey = computed(() => releaseDisplay.getExpansionKey(props.itemId))

// Get the releases to display
const displayedReleases = computed(() =>
  releaseDisplay.getDisplayReleases(props.releases, expansionKey.value)
)

// Handle toggle expansion
const handleToggleExpansion = () => {
  releaseDisplay.toggleReleaseExpansion(expansionKey.value)
}
</script>

<style scoped>
.releases-display {
  font-size: 0.875rem;
  line-height: 1.5;
}

.releases-list {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  margin: 0;
  padding: 0;
}

.release-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  text-decoration: none;
  color: #374151;
  padding: 0.25rem 0.5rem;
  margin: 0 -0.5rem;
  border-radius: 6px;
  transition: all 0.15s ease;
  font-size: 0.875rem;
  line-height: 1.5;
}

.release-link:hover {
  background: #f8fafc;
  color: #1e293b;
  text-decoration: none;
  transform: translateX(2px);
}

.product-name {
  font-weight: 500;
  color: inherit;
  flex: 1;
}

.version-info {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-shrink: 0;
}

.version-text {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Monaco, Consolas, monospace;
  font-size: 0.8125rem;
  color: #64748b;
  font-weight: 500;
  letter-spacing: -0.01em;
}

.version-text.is-latest {
  color: #059669;
  font-weight: 600;
}

.prerelease-label {
  font-size: 0.6875rem;
  color: #7c3aed;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  opacity: 0.8;
}

.release-expand {
  margin-top: 0.75rem;
  padding-top: 0.5rem;
  border-top: 1px solid #f1f5f9;
}

.expand-btn {
  background: none;
  border: none;
  color: #64748b;
  font-size: 0.8125rem;
  padding: 0.25rem 0.5rem;
  margin-left: -0.5rem;
  border-radius: 4px;
  transition: all 0.15s ease;
  cursor: pointer;
  font-weight: 500;
}

.expand-btn:hover {
  background: #f8fafc;
  color: #475569;
}

.release-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.view-all-btn {
  color: #3b82f6;
  font-size: 0.8125rem;
  font-weight: 500;
  text-decoration: none;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  transition: all 0.15s ease;
}

.view-all-btn:hover {
  background: #eff6ff;
  color: #2563eb;
  text-decoration: none;
}

.empty-releases {
  color: #9ca3af;
  font-size: 0.875rem;
  font-style: italic;
  padding: 0.5rem;
}
</style>