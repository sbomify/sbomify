<template>
  <ItemsListTable
    item-type="component"
    title="Components"
    :has-crud-permissions="hasCrudPermissions"
    :show-add-button="showAddButton"
  />
</template>

<script setup lang="ts">
import ItemsListTable from './ItemsListTable.vue'

interface Props {
  hasCrudPermissions?: boolean | string
  showAddButton?: boolean
}

withDefaults(defineProps<Props>(), {
  hasCrudPermissions: false,
  showAddButton: true
})
</script>