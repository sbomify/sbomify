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
/* Component uses global release styles from release-badges.css */
</style>