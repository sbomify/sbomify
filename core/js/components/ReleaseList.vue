<template>
  <div v-if="releases && releases.length > 0" class="releases-display">
    <div class="releases-list">
      <div
        v-for="release in displayedReleases"
        :key="release.id"
        class="release-item"
      >
        <a
          :href="releaseDisplay.getReleaseUrl(release)"
          class="release-link"
          :title="`View ${release.product_name} - ${release.name}`"
        >
          <span class="product-name">{{ release.product_name }}</span>:
          <span class="release-version">{{ release.is_latest ? 'latest' : release.name }}</span>
        </a>
      </div>

      <!-- Expansion controls -->
      <div v-if="releaseDisplay.shouldShowExpansion(releases)" class="release-expand">
        <button
          v-if="!releaseDisplay.shouldShowViewAll(releases)"
          class="btn btn-sm btn-link text-muted p-0"
          @click="handleToggleExpansion"
        >
          {{ releaseDisplay.getExpansionButtonText(releases, expansionKey) }}
        </button>
        <div v-else class="release-actions">
          <button
            class="btn btn-sm btn-link text-muted p-0"
            @click="handleToggleExpansion"
          >
            {{ releaseDisplay.getExpansionButtonText(releases, expansionKey) }}
          </button>
          <a
            v-if="viewAllUrl"
            :href="viewAllUrl"
            class="btn btn-sm btn-link text-primary p-0 ms-2"
            title="View all releases"
          >
            View all {{ releases.length }} releases →
          </a>
        </div>
      </div>
    </div>
  </div>
  <span v-else class="text-muted">None</span>
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
/* Fix bullet point alignment for release lists on product pages */
.releases-display {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.releases-list {
  margin: 0;
  padding-left: 1.5rem;
  list-style: none;
}

.release-item {
  position: relative;
  margin-bottom: 0.25rem;
  line-height: 1.5;
}

.release-item::before {
  content: "•";
  position: absolute;
  left: -1.25rem;
  top: 0;
  color: #6b7280;
  font-weight: bold;
  width: 1rem;
  text-align: center;
  line-height: 1.5;
}

.release-link {
  color: #3b82f6;
  text-decoration: none;
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  line-height: 1.5;
}

.release-link:hover {
  text-decoration: underline;
  color: #2563eb;
}

.product-name {
  font-weight: 500;
  color: #374151;
}

.release-version {
  color: #6b7280;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.8125rem;
  background: #f3f4f6;
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
}

.release-expand {
  margin-top: 0.25rem;
}

.release-expand button {
  font-size: 0.75rem;
  text-decoration: none;
  border: none;
  background: none;
}

.release-expand button:hover {
  text-decoration: underline;
}

.release-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.release-actions a {
  font-size: 0.75rem;
  text-decoration: none;
  border: none;
  background: none;
}

.release-actions a:hover {
  text-decoration: underline;
}
</style>