import hljs from 'highlight.js/lib/core';
import yaml from 'highlight.js/lib/languages/yaml';
import bash from 'highlight.js/lib/languages/bash';
import 'highlight.js/styles/github-dark.css';

// Register the languages
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('bash', bash);

interface Config {
    augment: boolean;
    enrich: boolean;
    outputFile: boolean;
}

interface Props {
    componentId: string;
    componentName: string;
    hasSboms: boolean;
}

import Alpine from '../../core/js/alpine-init';

export function registerCiCdInfo() {
    Alpine.data('ciCdInfo', (props: Props) => ({
        componentId: props.componentId,
        componentName: props.componentName,
        expanded: !props.hasSboms,
        activeTab: 'github',
        sourceType: 'lock',
        config: {
            augment: true,
            enrich: true,
            outputFile: true
        } as Config,
        tabs: [
            { id: 'github', name: 'GitHub', icon: 'fab fa-github' },
            { id: 'gitlab', name: 'GitLab', icon: 'fab fa-gitlab' },
            { id: 'bitbucket', name: 'Bitbucket', icon: 'fab fa-bitbucket' },
            { id: 'azure', name: 'Azure', icon: 'fab fa-microsoft' },
            { id: 'jenkins', name: 'Jenkins', icon: 'fab fa-jenkins' }
        ],
        tooltipInstances: [] as InstanceType<typeof window.bootstrap.Tooltip>[],

        init() {
            this.$watch('activeTab', () => this.updateContent());
            this.$watch('sourceType', () => this.updateContent());
            this.$watch('config.augment', () => this.updateContent());
            this.$watch('config.enrich', () => this.updateContent());
            this.$watch('config.outputFile', () => this.updateContent());

            this.$nextTick(() => {
                this.updateContent();
                this.initializeTooltips();
            });
        },

        destroy() {
            this.tooltipInstances.forEach(tooltip => {
                try {
                    tooltip.dispose();
                } catch {
                    // Tooltip may already be disposed
                }
            });
            this.tooltipInstances = [];
        },

        initializeTooltips() {
            if (!window.bootstrap) return;

            const tooltips = Array.from(this.$el.querySelectorAll('[data-bs-toggle="tooltip"]'));
            tooltips.forEach(el => {
                const existing = window.bootstrap.Tooltip.getInstance(el);
                if (!existing) {
                    const tooltip = new window.bootstrap.Tooltip(el);
                    this.tooltipInstances.push(tooltip);
                }
            });
        },

        handleTabClick(tabId: string) {
            this.activeTab = tabId;
        },

        updateContent() {
            let content = '';
            let language = 'yaml';

            switch (this.activeTab) {
                case 'github':
                    content = this.generateGithubYaml();
                    break;
                case 'gitlab':
                    content = this.generateGitlabYaml();
                    break;
                case 'bitbucket':
                    content = this.generateBitbucketYaml();
                    break;
                case 'azure':
                    content = this.generateAzureYaml();
                    break;
                case 'jenkins':
                    content = this.generateJenkinsfile();
                    language = 'bash';
                    break;
            }

            const codeBlock = this.$refs.codeBlock as HTMLElement | undefined;
            if (codeBlock) {
                codeBlock.innerHTML = hljs.highlight(content, { language }).value;
            }
        },

        generateGithubYaml(): string {
            const lines = [
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

            lines.push('        env:',
                `          TOKEN: \${{ secrets.SBOMIFY_TOKEN }}`,
                `          COMPONENT_ID: '${this.componentId}'`,
                `          COMPONENT_NAME: '${this.componentName}'`,
                `          COMPONENT_VERSION: \${{ github.ref_type == 'tag' && github.ref_name || format('{0}-{1}', github.ref_name, github.sha) }}`);

            // Add source-specific configuration
            switch (this.sourceType) {
                case 'sbom':
                    lines.push(`          SBOM_FILE: 'path/to/sbom.cdx.json'`);
                    break;
                case 'lock':
                    lines.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`);
                    break;
                case 'docker':
                    lines.push(`          DOCKER_IMAGE: 'your-image:tag'`);
                    break;
            }

            // Add boolean configurations
            if (this.config.augment) lines.push('          AUGMENT: true');
            if (this.config.enrich) lines.push('          ENRICH: true');
            if (this.config.outputFile) lines.push('          OUTPUT_FILE: sbom.cdx.json');

            return lines.join('\n');
        },

        generateGitlabYaml(): string {
            const lines = [
                'upload-sbom:',
                '  stage: deploy',
                '  image: sbomifyhub/sbomify-action'
            ];

            if (this.sourceType === 'docker') {
                lines.push('  services:',
                    '    - docker:dind',
                    '  variables:',
                    '    DOCKER_HOST: tcp://docker:2376',
                    '    DOCKER_TLS_VERIFY: 1',
                    '    DOCKER_CERT_PATH: /certs/client');
            }

            lines.push('  variables:',
                `    TOKEN: $SBOMIFY_TOKEN`,
                `    COMPONENT_ID: '${this.componentId}'`,
                `    COMPONENT_NAME: '${this.componentName}'`,
                `    COMPONENT_VERSION: \${CI_COMMIT_TAG:-$CI_COMMIT_REF_NAME-$CI_COMMIT_SHORT_SHA}`);

            switch (this.sourceType) {
                case 'sbom':
                    lines.push(`    SBOM_FILE: 'path/to/sbom.cdx.json'`);
                    break;
                case 'lock':
                    lines.push(`    LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`);
                    break;
                case 'docker':
                    lines.push(`    DOCKER_IMAGE: 'your-image:tag'        # Using Docker-in-Docker service`);
                    break;
            }

            if (this.config.augment) lines.push('    AUGMENT: true');
            if (this.config.enrich) lines.push('    ENRICH: true');
            if (this.config.outputFile) lines.push('    OUTPUT_FILE: sbom.cdx.json');

            lines.push('  script:', '    - sbomify-action');

            return lines.join('\n');
        },

        generateBitbucketYaml(): string {
            const lines = [
                'pipelines:',
                '  default:',
                '    - step:',
                '        name: Upload SBOM',
                '        image: sbomifyhub/sbomify-action',
                '        services:',
                '          - docker'
            ];

            if (this.sourceType === 'docker') {
                lines.push('        docker: true');
            }

            lines.push('        script:',
                '          - sbomify-action',
                '        env:',
                `          TOKEN: $SBOMIFY_TOKEN`,
                `          COMPONENT_ID: '${this.componentId}'`,
                `          COMPONENT_NAME: '${this.componentName}'`,
                `          COMPONENT_VERSION: \${BITBUCKET_TAG:-$BITBUCKET_BRANCH-$BITBUCKET_COMMIT}`);

            switch (this.sourceType) {
                case 'sbom':
                    lines.push(`          SBOM_FILE: 'path/to/sbom.cdx.json'`);
                    break;
                case 'lock':
                    lines.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`);
                    break;
                case 'docker':
                    lines.push(`          DOCKER_IMAGE: 'your-image:tag'        # Using Docker service`);
                    break;
            }

            if (this.config.augment) lines.push('          AUGMENT: true');
            if (this.config.enrich) lines.push('          ENRICH: true');
            if (this.config.outputFile) lines.push('          OUTPUT_FILE: sbom.cdx.json');

            return lines.join('\n');
        },

        generateAzureYaml(): string {
            const lines = [
                'trigger:',
                '  - main',
                '',
                'pool:',
                '  vmImage: ubuntu-latest',
                '',
                'steps:',
                '  - checkout: self',
                '',
                '  - script: |'
            ];

            // Build the docker run command
            const dockerLines: string[] = [];
            dockerLines.push('      docker run --rm -v $(Build.SourcesDirectory):/code \\');

            if (this.sourceType === 'docker') {
                dockerLines.push('        -v /var/run/docker.sock:/var/run/docker.sock \\');
            }

            dockerLines.push(
                '        -e TOKEN=$(SBOMIFY_TOKEN) \\',
                `        -e COMPONENT_ID='${this.componentId}' \\`,
                `        -e COMPONENT_NAME='${this.componentName}' \\`,
                '        -e COMPONENT_VERSION=$(Build.SourceBranchName)-$(Build.SourceVersion) \\'
            );

            // Add source-specific configuration
            switch (this.sourceType) {
                case 'sbom':
                    dockerLines.push(`        -e SBOM_FILE=/code/path/to/sbom.cdx.json \\`);
                    break;
                case 'lock':
                    dockerLines.push(`        -e LOCK_FILE=/code/poetry.lock \\     # Or package-lock.json, Gemfile.lock, etc.`);
                    break;
                case 'docker':
                    dockerLines.push(`        -e DOCKER_IMAGE='your-image:tag' \\`);
                    break;
            }

            // Add boolean configurations
            if (this.config.augment) dockerLines.push('        -e AUGMENT=true \\');
            if (this.config.enrich) dockerLines.push('        -e ENRICH=true \\');
            if (this.config.outputFile) dockerLines.push('        -e OUTPUT_FILE=/code/sbom.cdx.json \\');

            // Add the image name (remove trailing backslash from last line)
            const lastLine = dockerLines[dockerLines.length - 1];
            dockerLines[dockerLines.length - 1] = lastLine.replace(/ \\$/, '');
            dockerLines.push('        sbomifyhub/sbomify-action');

            lines.push(...dockerLines);

            lines.push(
                '    displayName: Upload SBOM',
                '    env:',
                '      SBOMIFY_TOKEN: $(SBOMIFY_TOKEN)'
            );

            return lines.join('\n');
        },

        generateJenkinsfile(): string {
            const lines = [
                'pipeline {',
                '    agent any',
                '',
                '    environment {',
                '        SBOMIFY_TOKEN = credentials(\'sbomify-token\')',
                `        COMPONENT_ID = '${this.componentId}'`,
                `        COMPONENT_NAME = '${this.componentName}'`,
                '    }',
                '',
                '    stages {',
                '        stage(\'Upload SBOM\') {',
                '            steps {',
                '                script {',
                '                    def version = env.TAG_NAME ?: "${env.BRANCH_NAME}-${env.GIT_COMMIT}"'
            ];

            // Build the docker run command
            lines.push('                    sh """');
            lines.push('                        docker run --rm -v $WORKSPACE:/code \\\\');

            if (this.sourceType === 'docker') {
                lines.push('                          -v /var/run/docker.sock:/var/run/docker.sock \\\\');
            }

            lines.push(
                '                          -e TOKEN=$SBOMIFY_TOKEN \\\\',
                '                          -e COMPONENT_ID=$COMPONENT_ID \\\\',
                '                          -e COMPONENT_NAME=$COMPONENT_NAME \\\\',
                '                          -e COMPONENT_VERSION=$version \\\\'
            );

            // Add source-specific configuration
            switch (this.sourceType) {
                case 'sbom':
                    lines.push('                          -e SBOM_FILE=/code/path/to/sbom.cdx.json \\\\');
                    break;
                case 'lock':
                    lines.push('                          -e LOCK_FILE=/code/poetry.lock \\\\');
                    break;
                case 'docker':
                    lines.push('                          -e DOCKER_IMAGE=\'your-image:tag\' \\\\');
                    break;
            }

            // Add boolean configurations
            if (this.config.augment) lines.push('                          -e AUGMENT=true \\\\');
            if (this.config.enrich) lines.push('                          -e ENRICH=true \\\\');
            if (this.config.outputFile) lines.push('                          -e OUTPUT_FILE=/code/sbom.cdx.json \\\\');

            // Remove trailing backslash from last line and add image
            const lastLine = lines[lines.length - 1];
            lines[lines.length - 1] = lastLine.replace(/ \\\\$/, '');
            lines.push('                          sbomifyhub/sbomify-action');

            lines.push(
                '                    """',
                '                }',
                '            }',
                '        }',
                '    }',
                '}'
            );

            return lines.join('\n');
        }
    }));
}
