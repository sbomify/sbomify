<template>
  <div>
    <div class="expression-builder">
      <template v-for="(segment, idx) in segments" :key="idx">
        <select v-model="segment.license" class="license-select" @change="onSegmentChange">
          <option value="" disabled>Select license...</option>
          <option v-for="id in licenseIds" :key="id" :value="id">{{ id }}</option>
        </select>
        <template v-if="segment.operator">
          <select v-model="segment.operator" class="operator-select" @change="onSegmentChange">
            <option value="AND">AND</option>
            <option value="OR">OR</option>
            <option value="WITH">WITH</option>
          </select>
        </template>
        <template v-if="segment.operator === 'WITH'">
          <select v-model="segment.exception" class="exception-select" @change="onSegmentChange">
            <option value="" disabled>Select exception...</option>
            <option v-for="ex in exceptionIds" :key="ex" :value="ex">{{ ex }}</option>
          </select>
        </template>
        <button v-if="segments.length > 1" @click="removeSegment(idx)">Remove</button>
        <span v-if="idx < segments.length - 1"> </span>
      </template>
      <button @click="addSegment">Add</button>
    </div>
    <div class="expression-preview">
      <strong>Composed:</strong> {{ composedExpression }}
    </div>
    <div v-if="validationError" class="invalid-feedback" style="display:block;">{{ validationError }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, defineEmits, onMounted } from 'vue';
import $axios from '../../../core/js/utils';

const licenseIds = ref<string[]>([]);
const exceptionIds = ref<string[]>([]);

const emits = defineEmits(['update:modelValue', 'validation']);

interface Segment {
  license: string;
  operator: string | null;
  exception: string | null;
}

const segments = ref<Segment[]>([
  { license: '', operator: null, exception: null }
]);

const composedExpression = ref('');
const validationError = ref<string | null>(null);

// TODO: The 'license' field is temporary and will be removed in the future.
// It will be generated ad-hoc from the view for backward compatibility.

async function fetchSpdxIdentifiers() {
  try {
    const response = await $axios.get('/api/v1/sboms/spdx_identifiers');
    if (response.data && Array.isArray(response.data.identifiers)) {
      // SPDX license IDs are those not ending with -exception or _exception
      licenseIds.value = response.data.identifiers.filter(
        (id: string) => !id.toLowerCase().includes('exception')
      );
      // Add Commons-Clause if not present
      if (!licenseIds.value.includes('Commons-Clause')) {
        licenseIds.value.push('Commons-Clause');
      }
      // SPDX exception IDs are those containing 'exception'
      exceptionIds.value = response.data.identifiers.filter(
        (id: string) => id.toLowerCase().includes('exception')
      );
    }
  } catch {
    licenseIds.value = [];
    exceptionIds.value = [];
  }
}

function addSegment() {
  // Only add if last segment is filled
  const last = segments.value[segments.value.length - 1];
  if (!last.license) return;
  segments.value.push({ license: '', operator: 'AND', exception: null });
}

function removeSegment(idx: number) {
  segments.value.splice(idx, 1);
  updateComposedExpression();
}

function onSegmentChange() {
  updateComposedExpression();
}

function updateComposedExpression() {
  let expr = '';
  segments.value.forEach((seg, idx) => {
    if (!seg.license) return;
    if (idx > 0 && seg.operator) expr += ` ${seg.operator} `;
    expr += seg.license;
    if (seg.operator === 'WITH' && seg.exception) {
      expr += ` WITH ${seg.exception}`;
    }
  });
  composedExpression.value = expr;
  emits('update:modelValue', expr);
  validateExpression(expr);
}

async function validateExpression(expr: string) {
  if (!expr) {
    validationError.value = null;
    emits('validation', null);
    return;
  }
  try {
    const response = await $axios.post('/api/v1/sboms/validate_license_expression', { expression: expr });
    if (!response.data.is_valid) {
      validationError.value = response.data.errors.join(', ');
      emits('validation', validationError.value);
    } else {
      validationError.value = null;
      emits('validation', null);
    }
  } catch {
    validationError.value = 'Error validating license expression.';
    emits('validation', validationError.value);
  }
}

watch(segments, updateComposedExpression, { deep: true });

onMounted(() => {
  fetchSpdxIdentifiers();
  updateComposedExpression();
});
</script>

<style scoped>
.expression-builder {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 1rem;
}
.license-select, .operator-select, .exception-select {
  min-width: 160px;
  padding: 0.5rem;
  border-radius: 4px;
  border: 1px solid #ccc;
}
.expression-preview {
  margin-bottom: 0.5rem;
}
.invalid-feedback {
  color: #dc3545;
  font-size: 0.9rem;
}
</style>