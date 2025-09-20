<template>
  <div class="modal fade show" tabindex="-1" style="display: block;" aria-modal="true" role="dialog">
    <div class="modal-dialog modal-dialog-centered" role="document">
      <div class="modal-content item-select-modal">
        <div class="modal-header">
          <h3 class="modal-title text-black">Select {{ titledItemType }}</h3>
          <button type="button" class="btn" data-bs-dismiss="modal" aria-label="Close"
                  @click="$emit('canceled')">
            X
          </button>
        </div>
        <div class="modal-body my-3">
          <div class=content-area>
            <table class="table table-striped table-hover">
              <thead>
              <tr>
                <th scope="col"></th>
                <th scope="col">{{ titledItemType }} ID</th>
                <th scope="col">Team</th>
                <th scope="col">{{ titledItemType }} Name</th>
              </tr>
              </thead>
              <tbody>
                <tr v-for="item in items" @click="model=item.item_key">
                  <td><input v-model="model" class="form-check-input" type="radio"
                       name="selected-item" :value="item.item_key"></td>
                  <td>{{ item.item_key }}</td>
                  <td>{{ item.team_name }}</td>
                  <td>{{ item.item_name }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Pagination Controls -->
          <PaginationControls
            v-if="shouldShowPagination"
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :total-pages="paginationMeta!.total_pages"
            :total-items="paginationMeta!.total"
            :show-page-size-selector="true"
          />
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-link text-black" data-bs-dismiss="modal" @click="$emit('canceled')">
            Cancel
          </button>
          <button type="button" class="btn btn-primary" @click="$emit('selected')">Select</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
  import $axios from '../../../core/js/utils';
  import { ref, onMounted, computed, watch } from 'vue';
  import type { UserItemsResponse } from '../type_defs';
  import PaginationControls from './PaginationControls.vue';

  interface Props {
    itemType: string;
    excludeItems?: string[];
  }

  const props = defineProps<Props>();
  const model = defineModel({type: String, default: ''});

  const items = ref<UserItemsResponse[]>([]);
  const paginationMeta = ref<{
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
    has_previous: boolean;
    has_next: boolean;
  } | null>(null);
  const currentPage = ref(1);
  const pageSize = ref(15);

  const titledItemType = computed(() => {
    return props.itemType.charAt(0).toUpperCase() + props.itemType.slice(1);
  });

  const apiUrl = '/api/v1/' + props.itemType + 's';

  const getUserItems = async () => {
    try {
      const params = new URLSearchParams({
        page: currentPage.value.toString(),
        page_size: pageSize.value.toString()
      });

      const response = await $axios.get(`${apiUrl}?${params}`);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      // Handle paginated response format
      const itemsData = response.data.items || response.data;
      paginationMeta.value = response.data.pagination || null;

      // Transform paginated items to UserItemsResponse format
      const transformedItems: UserItemsResponse[] = itemsData.map((item: {
        team_id: string;
        id: string;
        name: string;
      }) => ({
        team_key: item.team_id,
        team_name: 'Current Team', // We could get this from context if needed
        item_key: item.id,
        item_name: item.name
      }));

      if (props.excludeItems && props.excludeItems.length > 0) {
        items.value = transformedItems.filter((item: UserItemsResponse) => !props.excludeItems?.includes(item.item_key));
      } else {
        items.value = transformedItems;
      }

    } catch (error) {
      console.log(error)
    }
  }

  const shouldShowPagination = computed(() => {
    return paginationMeta.value && paginationMeta.value.total_pages > 1;
  });

  // Watch for pagination changes
  watch([currentPage, pageSize], () => {
    getUserItems();
  });

  onMounted(async () => {
    getUserItems();
  });

  defineEmits<{
    (e: 'canceled'): void;
    (e: 'selected'): void;
  }>();
</script>

<style lang="css" scoped>
  .modal {
    background-color: rgba(0, 0, 0, 0.3);
  }

  tbody > tr {
    cursor: pointer;
  }

  .item-select-modal {
    border-radius: 8px;
    border: 1px solid #D1D9E2;
    background: #FFF;
    box-shadow: 0px 2px 12px 0px rgba(145, 145, 145, 0.15);
  }

  .content-area {
    max-height: 70vh;
    overflow-y: auto;
  }

</style>