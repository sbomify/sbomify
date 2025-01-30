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
  import { ref, onMounted, computed } from 'vue';
  import type { UserItemsResponse } from '../type_defs';

  interface Props {
    itemType: string;
    excludeItems?: string[];
  }

  const props = defineProps<Props>();
  const model = defineModel({type: String, default: ''});

  const items = ref<UserItemsResponse[]>([]);

  const titledItemType = computed(() => {
    return props.itemType.charAt(0).toUpperCase() + props.itemType.slice(1);
  });

  const apiUrl = '/api/v1/sboms/user-items/' + props.itemType;

  const getUserItems = async () => {
    try {
      const response = await $axios.get(apiUrl);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Network response was not ok. ' + response.statusText);
      }

      if (props.excludeItems && props.excludeItems.length > 0) {
        items.value = response.data.filter((item: UserItemsResponse) => !props.excludeItems?.includes(item.item_key));
      } else {
        items.value = response.data;
      }

    } catch (error) {
      console.log(error)
    }
  }

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