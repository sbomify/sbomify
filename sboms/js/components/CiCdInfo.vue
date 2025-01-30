<template>
  <div class="card">
    <div class="card-body">
      <h4 class="d-flex justify-content-between align-items-center mb-4" style="cursor: pointer;" @click="toggleExpand">
        CI/CD Integration
        <svg v-if="!isExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
        <svg v-if="isExpanded" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </h4>
      <div v-if="isExpanded" class="mb-4">
        <!-- Source Selector -->
        <div class="source-selector mb-3">
          <label for="source-select" class="form-label">SBOM Source</label>
          <select id="source-select" v-model="sourceType" class="form-select">
            <option value="sbom">Existing SBOM file</option>
            <option value="lock">Generate from lock file</option>
            <option value="docker">Generate from Docker image</option>
          </select>
        </div>

        <!-- Configuration Options -->
        <div class="config-options">
          <div class="config-option">
            <div class="form-check">
              <input id="augment" v-model="config.augment" type="checkbox" class="form-check-input">
              <label for="augment" class="form-check-label">
                Augment
                <span class="info-icon" data-bs-toggle="tooltip" data-bs-placement="top"
                   title="Add component metadata from the Component Metadata section above to provide additional context about your software">i</span>
              </label>
            </div>
          </div>
          <div class="config-option">
            <div class="form-check">
              <input id="enrich" v-model="config.enrich" type="checkbox" class="form-check-input">
              <label for="enrich" class="form-check-label">
                Enrich
                <span class="info-icon" data-bs-toggle="tooltip" data-bs-placement="top"
                   title="Automatically improve SBOM quality by adding additional data like licenses from package registries and other sources">i</span>
              </label>
            </div>
          </div>
          <div class="config-option">
            <div class="form-check">
              <input id="override-meta" v-model="config.overrideMeta" type="checkbox" class="form-check-input">
              <label for="override-meta" class="form-check-label">
                Override SBOM metadata
                <span class="info-icon" data-bs-toggle="tooltip" data-bs-placement="top"
                   title="Override default SBOM metadata with custom values for organization-specific information">i</span>
              </label>
            </div>
          </div>
          <div class="config-option">
            <div class="form-check">
              <input id="output-file" v-model="config.outputFile" type="checkbox" class="form-check-input">
              <label for="output-file" class="form-check-label">
                Save SBOM to file
                <span class="info-icon" data-bs-toggle="tooltip" data-bs-placement="top"
                   title="Save the generated SBOM to a local file in addition to uploading it">i</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Token requirement note -->
        <div class="alert alert-info mb-3 d-flex align-items-center">
          <div class="alert-icon me-3">
            <i class="fas fa-key"></i>
          </div>
          <div class="alert-content">
            <strong>Required:</strong> Before using any CI integration, create a secret named <code>SBOMIFY_TOKEN</code> containing your API token. You can find your token in your account settings.
          </div>
        </div>

        <!-- Tabs -->
        <div class="nav-tabs-container">
          <ul class="nav nav-tabs" role="tablist">
            <li class="nav-item" role="presentation">
              <button id="github-tab" class="nav-link active" data-bs-toggle="tab" data-bs-target="#github"
                      type="button" role="tab" aria-controls="github" aria-selected="true"
                      @click="handleTabClick('github')">
                <i class="fab fa-github me-1"></i>GitHub
              </button>
            </li>
            <li class="nav-item" role="presentation">
              <button id="gitlab-tab" class="nav-link" data-bs-toggle="tab" data-bs-target="#gitlab"
                      type="button" role="tab" aria-controls="gitlab" aria-selected="false"
                      @click="handleTabClick('gitlab')">
                <i class="fab fa-gitlab me-1"></i>GitLab
              </button>
            </li>
            <li class="nav-item" role="presentation">
              <button id="bitbucket-tab" class="nav-link" data-bs-toggle="tab" data-bs-target="#bitbucket"
                      type="button" role="tab" aria-controls="bitbucket" aria-selected="false"
                      @click="handleTabClick('bitbucket')">
                <i class="fab fa-bitbucket me-1"></i>Bitbucket
              </button>
            </li>
            <li class="nav-item" role="presentation">
              <button id="docker-tab" class="nav-link" data-bs-toggle="tab" data-bs-target="#docker"
                      type="button" role="tab" aria-controls="docker" aria-selected="false"
                      @click="handleTabClick('docker')">
                <i class="fab fa-docker me-1"></i>Docker
              </button>
            </li>
          </ul>

          <div class="tab-content">
            <!-- GitHub Tab -->
            <div id="github" class="tab-pane fade show active" role="tabpanel" aria-labelledby="github-tab">
              <template v-if="activeTab === 'github'">
                <div class="code-block">
                  <pre><code ref="githubCode" class="language-yaml hljs"></code></pre>
                  <div class="copy-btn">
                    <CopyableValue :value="githubContent" title="Copy GitHub workflow" hide-value />
                  </div>
                </div>
              </template>
            </div>

            <!-- GitLab Tab -->
            <div id="gitlab" class="tab-pane fade" role="tabpanel" aria-labelledby="gitlab-tab">
              <template v-if="activeTab === 'gitlab'">
                <div class="code-block">
                  <pre><code ref="gitlabCode" class="language-yaml hljs"></code></pre>
                  <div class="copy-btn">
                    <CopyableValue :value="gitlabContent" title="Copy GitLab CI config" hide-value />
                  </div>
                </div>
              </template>
            </div>

            <!-- Bitbucket Tab -->
            <div id="bitbucket" class="tab-pane fade" role="tabpanel" aria-labelledby="bitbucket-tab">
              <template v-if="activeTab === 'bitbucket'">
                <div class="code-block">
                  <pre><code ref="bitbucketCode" class="language-yaml hljs"></code></pre>
                  <div class="copy-btn">
                    <CopyableValue :value="bitbucketContent" title="Copy Bitbucket pipeline" hide-value />
                  </div>
                </div>
              </template>
            </div>

            <!-- Docker Tab -->
            <div id="docker" class="tab-pane fade" role="tabpanel" aria-labelledby="docker-tab">
              <template v-if="sourceType === 'docker'">
                <!-- GitHub note -->
                <div v-if="activeTab === 'github'" class="alert alert-info mb-3 d-flex align-items-center">
                  <div class="alert-icon me-3">
                    <i class="fas fa-info-circle"></i>
                  </div>
                  <div class="alert-content">
                    <strong>Note:</strong> For Docker image scanning in GitHub Actions, the action will use GitHub's built-in Docker support. No additional configuration is needed.
                  </div>
                </div>

                <!-- GitLab note -->
                <div v-if="activeTab === 'gitlab'" class="alert alert-warning mb-3 d-flex align-items-center">
                  <div class="alert-icon me-3">
                    <i class="fas fa-exclamation-triangle"></i>
                  </div>
                  <div class="alert-content">
                    <strong>Note:</strong> GitLab CI requires Docker-in-Docker (DinD) service for Docker image scanning. The configuration above includes the necessary DinD setup.
                  </div>
                </div>

                <!-- Bitbucket note -->
                <div v-if="activeTab === 'bitbucket'" class="alert alert-info mb-3 d-flex align-items-center">
                  <div class="alert-icon me-3">
                    <i class="fas fa-info-circle"></i>
                  </div>
                  <div class="alert-content">
                    <strong>Note:</strong> Bitbucket Pipelines provides built-in Docker support. The configuration above includes the necessary Docker service setup.
                  </div>
                </div>

                <!-- Docker CLI note -->
                <div v-if="activeTab === 'docker'" class="alert alert-info mb-3 d-flex align-items-center">
                  <div class="alert-icon me-3">
                    <i class="fas fa-info-circle"></i>
                  </div>
                  <div class="alert-content">
                    <strong>Note:</strong> For local Docker scanning, the Docker socket is mounted automatically when using Docker CLI.
                  </div>
                </div>
              </template>
              <template v-if="activeTab === 'docker'">
                <div class="code-block">
                  <pre><code ref="dockerCode" class="language-shell hljs"></code></pre>
                  <div class="copy-btn">
                    <CopyableValue :value="dockerContent" title="Copy Docker command" hide-value />
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue';
import hljs from 'highlight.js/lib/core';
import yaml from 'highlight.js/lib/languages/yaml';
import bash from 'highlight.js/lib/languages/bash';
import 'highlight.js/styles/github-dark.css';
import CopyableValue from '../../../core/js/components/CopyableValue.vue';

interface BootstrapTooltipOptions {
  placement?: 'top' | 'bottom' | 'left' | 'right';
  trigger?: string;
  title?: string;
  container?: string | boolean | Element;
  animation?: boolean;
}

interface BootstrapTooltip {
  dispose(): void;
  enable(): void;
  disable(): void;
  toggleEnabled(): void;
  toggle(): void;
  show(): void;
  hide(): void;
}

declare global {
  interface Window {
    bootstrap: {
      Tooltip: new (element: Element, options?: BootstrapTooltipOptions) => BootstrapTooltip;
    };
  }
}

// Register the languages
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('bash', bash);

interface Props {
  componentId: string;
}

const props = defineProps<Props>();
const isExpanded = ref(false);
const sourceType = ref('sbom');
const config = ref({
  augment: false,
  enrich: false,
  overrideMeta: false,
  outputFile: false
});

// Refs for code blocks
const githubCode = ref<HTMLElement | null>(null);
const gitlabCode = ref<HTMLElement | null>(null);
const bitbucketCode = ref<HTMLElement | null>(null);
const dockerCode = ref<HTMLElement | null>(null);

// Content generator functions
const generateGithubYaml = () => {
  const yaml = [
    'name: Upload SBOM',
    'on:',
    '  push:',
    '    branches: [ main ]',
    '',
    'jobs:',
    '  upload-sbom:',
    '    runs-on: ubuntu-latest',
    '    steps:',
    '      - uses: actions/checkout@v4',
    '',
    '      - name: Upload SBOM',
    '        uses: sbomify/github-action@master'
  ];

  yaml.push('        env:',
            `          TOKEN: \${{ secrets.SBOMIFY_TOKEN }}`,
            `          COMPONENT_ID: '${props.componentId}'`);

  // Add source-specific configuration
  switch (sourceType.value) {
    case 'sbom':
      yaml.push(`          SBOM_FILE: 'path/to/sbom.json'`);
      break;
    case 'lock':
      yaml.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`);
      break;
    case 'docker':
      yaml.push(`          DOCKER_IMAGE: 'your-image:tag'`);
      break;
  }

  // Add boolean configurations
  if (config.value.augment) yaml.push('          AUGMENT: true');
  if (config.value.enrich) yaml.push('          ENRICH: true');
  if (config.value.overrideMeta) yaml.push('          OVERRIDE_SBOM_METADATA: true');
  if (config.value.outputFile) yaml.push('          OUTPUT_FILE: sbom.json');

  return yaml.join('\n');
};

const generateGitlabYaml = () => {
  const yaml = [
    'upload-sbom:',
    '  stage: deploy',
    '  image: sbomifyhub/sbomify-action'
  ];

  if (sourceType.value === 'docker') {
    yaml.push('  services:',
             '    - docker:dind',
             '  variables:',
             '    DOCKER_HOST: tcp://docker:2376',
             '    DOCKER_TLS_VERIFY: 1',
             '    DOCKER_CERT_PATH: /certs/client');
  }

  yaml.push('  variables:',
            `    TOKEN: \$SBOMIFY_TOKEN`,
            `    COMPONENT_ID: '${props.componentId}'`);

  switch (sourceType.value) {
    case 'sbom':
      yaml.push(`    SBOM_FILE: 'path/to/sbom.json'`);
      break;
    case 'lock':
      yaml.push(`    LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`);
      break;
    case 'docker':
      yaml.push(`    DOCKER_IMAGE: 'your-image:tag'        # Using Docker-in-Docker service`);
      break;
  }

  if (config.value.augment) yaml.push('    AUGMENT: true');
  if (config.value.enrich) yaml.push('    ENRICH: true');
  if (config.value.overrideMeta) yaml.push('    OVERRIDE_SBOM_METADATA: true');
  if (config.value.outputFile) yaml.push('    OUTPUT_FILE: sbom.json');

  yaml.push('  script:', '    - /entrypoint.sh');

  return yaml.join('\n');
};

const generateBitbucketYaml = () => {
  const yaml = [
    'pipelines:',
    '  default:',
    '    - step:',
    '        name: Upload SBOM',
    '        image: sbomifyhub/sbomify-action',
    '        services:',
    '          - docker'
  ];

  if (sourceType.value === 'docker') {
    yaml.push('        docker: true');
  }

  yaml.push('        script:',
            '          - /entrypoint.sh',
            '        env:',
            `          TOKEN: \$SBOMIFY_TOKEN`,
            `          COMPONENT_ID: '${props.componentId}'`);

  switch (sourceType.value) {
    case 'sbom':
      yaml.push(`          SBOM_FILE: 'path/to/sbom.json'`);
      break;
    case 'lock':
      yaml.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`);
      break;
    case 'docker':
      yaml.push(`          DOCKER_IMAGE: 'your-image:tag'        # Using Docker service`);
      break;
  }

  if (config.value.augment) yaml.push('          AUGMENT: true');
  if (config.value.enrich) yaml.push('          ENRICH: true');
  if (config.value.overrideMeta) yaml.push('          OVERRIDE_SBOM_METADATA: true');
  if (config.value.outputFile) yaml.push('          OUTPUT_FILE: sbom.json');

  return yaml.join('\n');
};

const generateDockerCommand = () => {
  const cmd = [
    '# Pull and run the sbomify action container',
    'docker run -it --rm \\'
  ];

  if (sourceType.value === 'docker') {
    cmd.push('  -v /var/run/docker.sock:/var/run/docker.sock \\');
  }

  cmd.push('  -e TOKEN=$SBOMIFY_TOKEN \\',
          `  -e COMPONENT_ID=${props.componentId} \\`);

  switch (sourceType.value) {
    case 'sbom':
      cmd.push('  -v $(pwd)/path/to/sbom.json:/sbom.json \\',
              '  -e SBOM_FILE=/sbom.json \\');
      break;
    case 'lock':
      cmd.push('  -v $(pwd)/poetry.lock:/app/poetry.lock \\',
              '  -e LOCK_FILE=/app/poetry.lock \\');
      break;
    case 'docker':
      cmd.push('  -e DOCKER_IMAGE=your-image:tag \\');
      break;
  }

  if (config.value.augment) cmd.push('  -e AUGMENT=true \\');
  if (config.value.enrich) cmd.push('  -e ENRICH=true \\');
  if (config.value.overrideMeta) cmd.push('  -e OVERRIDE_SBOM_METADATA=true \\');
  if (config.value.outputFile) cmd.push('  -e OUTPUT_FILE=sbom.json \\');

  cmd.push('  sbomifyhub/sbomify-action');

  return cmd.join('\n');
};

// Raw content generators
const githubContent = computed(() => generateGithubYaml());
const gitlabContent = computed(() => generateGitlabYaml());
const bitbucketContent = computed(() => generateBitbucketYaml());
const dockerContent = computed(() => generateDockerCommand());

// Watch for content changes and update highlighting
watch([githubContent, gitlabContent, bitbucketContent, dockerContent], () => {
  nextTick(() => {
    updateHighlighting();
  });
});

// Function to update syntax highlighting
const updateHighlighting = () => {
  if (githubCode.value) {
    githubCode.value.innerHTML = hljs.highlight(githubContent.value, { language: 'yaml' }).value;
  }
  if (gitlabCode.value) {
    gitlabCode.value.innerHTML = hljs.highlight(gitlabContent.value, { language: 'yaml' }).value;
  }
  if (bitbucketCode.value) {
    bitbucketCode.value.innerHTML = hljs.highlight(bitbucketContent.value, { language: 'yaml' }).value;
  }
  if (dockerCode.value) {
    dockerCode.value.innerHTML = hljs.highlight(dockerContent.value, { language: 'bash' }).value;
  }
};

const toggleExpand = () => {
  isExpanded.value = !isExpanded.value;
  // Update highlighting when expanded
  if (isExpanded.value) {
    nextTick(() => {
      updateHighlighting();
    });
  }
};

// Initialize clipboard and highlighting
onMounted(() => {
  nextTick(() => {
    updateHighlighting();

    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(tooltipTriggerEl => new window.bootstrap.Tooltip(tooltipTriggerEl));
  });
});

// Add activeTab ref
const activeTab = ref('github');

// Add tab click handler
const handleTabClick = (tab: string) => {
  activeTab.value = tab;
  nextTick(() => {
    updateHighlighting();
  });
};
</script>

<style scoped>
.code-block {
  position: relative;
  background: #0d1117;
  border-radius: 0.5rem;
  overflow: hidden;
}

.code-block pre {
  margin: 0;
  padding: 1.25rem;
  background: transparent;
}

.code-block code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace;
  font-size: 0.875rem;
  line-height: 1.6;
  color: #e6e6e6;
}

.copy-btn {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  padding: 0.25rem 0.5rem;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 4px;
  color: #fff;
  transition: all 0.2s ease;
}

.copy-btn :deep(a) {
  color: #fff;
  display: flex;
  align-items: center;
}

.copy-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.copy-btn :deep(.copied) {
  display: none;
}

.nav-tabs .nav-link {
  padding: 0.75rem 1.25rem;
  border: none;
  border-bottom: 2px solid transparent;
  color: #6c757d;
}

.nav-tabs .nav-link.active {
  border: none;
  border-bottom: 2px solid #0d6efd;
  color: #0d6efd;
  background: transparent;
}

.tab-content {
  background: transparent !important;
  border: none !important;
  padding: 1rem 0 !important;
}

.source-selector {
  max-width: 300px;
}

.source-selector select {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #dee2e6;
  border-radius: 0.375rem;
  background-color: #fff;
  cursor: pointer;
}

.config-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin: 1.5rem 0;
  padding: 0;
  background: transparent;
  border-radius: 0;
}

.config-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.form-check {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  width: 100%;
}

.form-check-input {
  margin: 0;
  cursor: pointer;
}

.form-check-label {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  margin: 0;
  font-size: 0.875rem;
  color: #495057;
  cursor: pointer;
  user-select: none;
}

.info-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background-color: #6c757d;
  color: white;
  font-size: 10px;
  cursor: help;
}

.alert {
  border: none;
  border-radius: 0.5rem;
  padding: 1rem;
  font-size: 0.875rem;
  line-height: 1.5;
  margin: 0;
}

.alert-warning {
  background-color: rgba(255, 171, 0, 0.1);
  color: #93700c;
}

.alert-icon {
  font-size: 1.25rem;
  color: #f59e0b;
  flex-shrink: 0;
}

.alert-content {
  flex-grow: 1;
}

:deep(.hljs) {
  background: transparent;
  padding: 0;
}

/* Add specific syntax highlighting styles */
.hljs {
  display: block;
  overflow-x: auto;
  padding: 1em;
  color: #abb2bf;
  background: #282c34;
}

.hljs-comment,
.hljs-quote {
  color: #5c6370;
  font-style: italic;
}

.hljs-doctag,
.hljs-keyword,
.hljs-formula {
  color: #c678dd;
}

.hljs-section,
.hljs-name,
.hljs-selector-tag,
.hljs-deletion,
.hljs-subst {
  color: #e06c75;
}

.hljs-literal {
  color: #56b6c2;
}

.hljs-string,
.hljs-regexp,
.hljs-addition,
.hljs-attribute,
.hljs-meta .hljs-string {
  color: #98c379;
}

.hljs-attr,
.hljs-variable,
.hljs-template-variable,
.hljs-type,
.hljs-selector-class,
.hljs-selector-attr,
.hljs-selector-pseudo,
.hljs-number {
  color: #d19a66;
}

.hljs-symbol,
.hljs-bullet,
.hljs-link,
.hljs-meta,
.hljs-selector-id,
.hljs-title {
  color: #61aeee;
}

.hljs-built_in,
.hljs-title.class_,
.hljs-class .hljs-title {
  color: #e6c07b;
}

.hljs-emphasis {
  font-style: italic;
}

.hljs-strong {
  font-weight: bold;
}

.card {
  border: 1px solid #dee2e6;
  border-radius: 0.5rem;
  margin-bottom: 1rem;
}

.card-body {
  padding: 1.25rem;
}

.card-title {
  margin-bottom: 1rem;
  font-size: 1rem;
  font-weight: 500;
}

.config-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin: 1.5rem 0;
  padding: 0;
  background: transparent;
  border-radius: 0;
}

.config-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.form-check {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  width: 100%;
}

.form-check-input {
  margin: 0;
  cursor: pointer;
}

.form-check-label {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  margin: 0;
  font-size: 0.875rem;
  color: #495057;
  cursor: pointer;
  user-select: none;
}

.info-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background-color: #6c757d;
  color: white;
  font-size: 10px;
  cursor: help;
}

/* Remove nested boxes */
:deep(.card .card) {
  border: none;
  box-shadow: none;
  background: transparent;
  margin: 0;
}

:deep(.card .card-body) {
  padding: 0;
}

:deep(.card .card-title) {
  padding: 0;
  margin-bottom: 1rem;
  border-bottom: 1px solid #dee2e6;
  padding-bottom: 0.5rem;
}
</style>