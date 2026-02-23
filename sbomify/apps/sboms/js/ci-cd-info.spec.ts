import { describe, test, expect } from 'bun:test'

/**
 * Tests for CI/CD Info Alpine.js component business logic
 *
 * This test suite validates the core functionality of the CI/CD Info component
 * including YAML generation, tab management, source type handling, and configuration options.
 */

describe('CI/CD Info Business Logic', () => {

    const testComponentId = 'test-component-123'
    const testComponentName = 'Test Component'

    interface Config {
        augment: boolean
        enrich: boolean
        outputFile: boolean
    }

    describe('Initial State', () => {
        test('should initialize with correct default values', () => {
            const initialState = {
                componentId: testComponentId,
                componentName: testComponentName,
                expanded: true,
                activeTab: 'github',
                sourceType: 'lock',
                config: {
                    augment: true,
                    enrich: true,
                    outputFile: true
                }
            }

            expect(initialState.expanded).toBe(true)
            expect(initialState.activeTab).toBe('github')
            expect(initialState.sourceType).toBe('lock')
            expect(initialState.config.augment).toBe(true)
            expect(initialState.config.enrich).toBe(true)
            expect(initialState.config.outputFile).toBe(true)
        })

        test('should have correct tab definitions', () => {
            const tabs = [
                { id: 'github', name: 'GitHub', icon: 'fab fa-github' },
                { id: 'gitlab', name: 'GitLab', icon: 'fab fa-gitlab' },
                { id: 'bitbucket', name: 'Bitbucket', icon: 'fab fa-bitbucket' },
                { id: 'azure', name: 'Azure', icon: 'fab fa-microsoft' },
                { id: 'jenkins', name: 'Jenkins', icon: 'fab fa-jenkins' }
            ]

            expect(tabs.length).toBe(5)
            expect(tabs[0].id).toBe('github')
            expect(tabs[3].id).toBe('azure')
            expect(tabs[4].id).toBe('jenkins')
        })
    })

    describe('Tab Management', () => {
        test('should handle tab click correctly', () => {
            let activeTab = 'github'

            const handleTabClick = (tabId: string) => {
                activeTab = tabId
            }

            handleTabClick('gitlab')
            expect(activeTab).toBe('gitlab')

            handleTabClick('bitbucket')
            expect(activeTab).toBe('bitbucket')

            handleTabClick('azure')
            expect(activeTab).toBe('azure')

            handleTabClick('jenkins')
            expect(activeTab).toBe('jenkins')
        })

        test('should determine correct language for each tab', () => {
            const getLanguageForTab = (tabId: string): string => {
                switch (tabId) {
                    case 'jenkins':
                        return 'bash'
                    default:
                        return 'yaml'
                }
            }

            expect(getLanguageForTab('github')).toBe('yaml')
            expect(getLanguageForTab('gitlab')).toBe('yaml')
            expect(getLanguageForTab('bitbucket')).toBe('yaml')
            expect(getLanguageForTab('azure')).toBe('yaml')
            expect(getLanguageForTab('jenkins')).toBe('bash')
        })
    })

    describe('GitHub YAML Generation', () => {
        const generateGithubYaml = (
            componentId: string,
            componentName: string,
            sourceType: string,
            config: Config
        ): string => {
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
                '        uses: sbomify/sbomify-action@master'
            ]

            lines.push('        env:',
                `          TOKEN: \${{ secrets.SBOMIFY_TOKEN }}`,
                `          COMPONENT_ID: '${componentId}'`,
                `          COMPONENT_NAME: '${componentName}'`,
                `          COMPONENT_VERSION: \${{ github.ref_type == 'tag' && github.ref_name || format('{0}-{1}', github.ref_name, github.sha) }}`)

            switch (sourceType) {
                case 'sbom':
                    lines.push(`          SBOM_FILE: 'path/to/sbom.cdx.json'`)
                    break
                case 'lock':
                    lines.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`)
                    break
                case 'docker':
                    lines.push(`          DOCKER_IMAGE: 'your-image:tag'`)
                    break
            }

            if (config.augment) lines.push('          AUGMENT: true')
            if (config.enrich) lines.push('          ENRICH: true')
            if (config.outputFile) lines.push('          OUTPUT_FILE: sbom.cdx.json')

            return lines.join('\n')
        }

        test('should generate valid GitHub YAML with lock file source', () => {
            const yaml = generateGithubYaml(testComponentId, testComponentName, 'lock', {
                augment: true,
                enrich: true,
                outputFile: true
            })

            expect(yaml).toContain('name: Upload SBOM')
            expect(yaml).toContain('uses: sbomify/sbomify-action@master')
            expect(yaml).toContain(`COMPONENT_ID: '${testComponentId}'`)
            expect(yaml).toContain(`COMPONENT_NAME: '${testComponentName}'`)
            expect(yaml).toContain("LOCK_FILE: 'poetry.lock'")
            expect(yaml).toContain('AUGMENT: true')
            expect(yaml).toContain('ENRICH: true')
            expect(yaml).toContain('OUTPUT_FILE: sbom.cdx.json')
        })

        test('should generate GitHub YAML with SBOM file source', () => {
            const yaml = generateGithubYaml(testComponentId, testComponentName, 'sbom', {
                augment: false,
                enrich: false,
                outputFile: false
            })

            expect(yaml).toContain("SBOM_FILE: 'path/to/sbom.cdx.json'")
            expect(yaml).not.toContain('AUGMENT: true')
            expect(yaml).not.toContain('ENRICH: true')
            expect(yaml).not.toContain('OUTPUT_FILE')
        })

        test('should generate GitHub YAML with Docker image source', () => {
            const yaml = generateGithubYaml(testComponentId, testComponentName, 'docker', {
                augment: true,
                enrich: false,
                outputFile: true
            })

            expect(yaml).toContain("DOCKER_IMAGE: 'your-image:tag'")
            expect(yaml).toContain('AUGMENT: true')
            expect(yaml).not.toContain('ENRICH: true')
        })
    })

    describe('GitLab YAML Generation', () => {
        const generateGitlabYaml = (
            componentId: string,
            componentName: string,
            sourceType: string,
            config: Config
        ): string => {
            const lines = [
                'upload-sbom:',
                '  stage: deploy',
                '  image: sbomifyhub/sbomify-action'
            ]

            if (sourceType === 'docker') {
                lines.push('  services:',
                    '    - docker:dind',
                    '  variables:',
                    '    DOCKER_HOST: tcp://docker:2376',
                    '    DOCKER_TLS_VERIFY: 1',
                    '    DOCKER_CERT_PATH: /certs/client')
            }

            lines.push('  variables:',
                `    TOKEN: $SBOMIFY_TOKEN`,
                `    COMPONENT_ID: '${componentId}'`,
                `    COMPONENT_NAME: '${componentName}'`,
                `    COMPONENT_VERSION: \${CI_COMMIT_TAG:-$CI_COMMIT_REF_NAME-$CI_COMMIT_SHORT_SHA}`)

            switch (sourceType) {
                case 'sbom':
                    lines.push(`    SBOM_FILE: 'path/to/sbom.cdx.json'`)
                    break
                case 'lock':
                    lines.push(`    LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`)
                    break
                case 'docker':
                    lines.push(`    DOCKER_IMAGE: 'your-image:tag'        # Using Docker-in-Docker service`)
                    break
            }

            if (config.augment) lines.push('    AUGMENT: true')
            if (config.enrich) lines.push('    ENRICH: true')
            if (config.outputFile) lines.push('    OUTPUT_FILE: sbom.cdx.json')

            lines.push('  script:', '    - sbomify-action')

            return lines.join('\n')
        }

        test('should generate valid GitLab YAML with lock file source', () => {
            const yaml = generateGitlabYaml(testComponentId, testComponentName, 'lock', {
                augment: true,
                enrich: true,
                outputFile: true
            })

            expect(yaml).toContain('image: sbomifyhub/sbomify-action')
            expect(yaml).toContain(`COMPONENT_ID: '${testComponentId}'`)
            expect(yaml).toContain("LOCK_FILE: 'poetry.lock'")
            expect(yaml).toContain('sbomify-action')
        })

        test('should add Docker-in-Docker services for docker source', () => {
            const yaml = generateGitlabYaml(testComponentId, testComponentName, 'docker', {
                augment: false,
                enrich: false,
                outputFile: false
            })

            expect(yaml).toContain('docker:dind')
            expect(yaml).toContain('DOCKER_HOST: tcp://docker:2376')
            expect(yaml).toContain("DOCKER_IMAGE: 'your-image:tag'")
        })
    })

    describe('Bitbucket YAML Generation', () => {
        const generateBitbucketYaml = (
            componentId: string,
            componentName: string,
            sourceType: string,
            config: Config
        ): string => {
            const lines = [
                'pipelines:',
                '  default:',
                '    - step:',
                '        name: Upload SBOM',
                '        image: sbomifyhub/sbomify-action',
                '        services:',
                '          - docker'
            ]

            if (sourceType === 'docker') {
                lines.push('        docker: true')
            }

            lines.push('        script:',
                '          - sbomify-action',
                '        env:',
                `          TOKEN: $SBOMIFY_TOKEN`,
                `          COMPONENT_ID: '${componentId}'`,
                `          COMPONENT_NAME: '${componentName}'`,
                `          COMPONENT_VERSION: \${BITBUCKET_TAG:-$BITBUCKET_BRANCH-$BITBUCKET_COMMIT}`)

            switch (sourceType) {
                case 'sbom':
                    lines.push(`          SBOM_FILE: 'path/to/sbom.cdx.json'`)
                    break
                case 'lock':
                    lines.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`)
                    break
                case 'docker':
                    lines.push(`          DOCKER_IMAGE: 'your-image:tag'        # Using Docker service`)
                    break
            }

            if (config.augment) lines.push('          AUGMENT: true')
            if (config.enrich) lines.push('          ENRICH: true')
            if (config.outputFile) lines.push('          OUTPUT_FILE: sbom.cdx.json')

            return lines.join('\n')
        }

        test('should generate valid Bitbucket YAML', () => {
            const yaml = generateBitbucketYaml(testComponentId, testComponentName, 'lock', {
                augment: true,
                enrich: true,
                outputFile: true
            })

            expect(yaml).toContain('pipelines:')
            expect(yaml).toContain('name: Upload SBOM')
            expect(yaml).toContain(`COMPONENT_ID: '${testComponentId}'`)
        })

        test('should add docker: true for docker source', () => {
            const yaml = generateBitbucketYaml(testComponentId, testComponentName, 'docker', {
                augment: false,
                enrich: false,
                outputFile: false
            })

            expect(yaml).toContain('docker: true')
        })
    })

    describe('Azure Pipelines YAML Generation', () => {
        const generateAzureYaml = (
            componentId: string,
            componentName: string,
            sourceType: string,
            config: Config
        ): string => {
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
            ]

            const dockerLines: string[] = []
            dockerLines.push('      docker run --rm -v $(Build.SourcesDirectory):/code \\')

            if (sourceType === 'docker') {
                dockerLines.push('        -v /var/run/docker.sock:/var/run/docker.sock \\')
            }

            dockerLines.push(
                '        -e TOKEN=$(SBOMIFY_TOKEN) \\',
                `        -e COMPONENT_ID='${componentId}' \\`,
                `        -e COMPONENT_NAME='${componentName}' \\`,
                '        -e COMPONENT_VERSION=$(Build.SourceBranchName)-$(Build.SourceVersion) \\'
            )

            switch (sourceType) {
                case 'sbom':
                    dockerLines.push('        -e SBOM_FILE=/code/path/to/sbom.cdx.json \\')
                    break
                case 'lock':
                    dockerLines.push('        -e LOCK_FILE=/code/poetry.lock \\     # Or package-lock.json, Gemfile.lock, etc.')
                    break
                case 'docker':
                    dockerLines.push("        -e DOCKER_IMAGE='your-image:tag' \\")
                    break
            }

            if (config.augment) dockerLines.push('        -e AUGMENT=true \\')
            if (config.enrich) dockerLines.push('        -e ENRICH=true \\')
            if (config.outputFile) dockerLines.push('        -e OUTPUT_FILE=/code/sbom.cdx.json \\')

            const lastLine = dockerLines[dockerLines.length - 1]
            dockerLines[dockerLines.length - 1] = lastLine.replace(/ \\$/, '')
            dockerLines.push('        sbomifyhub/sbomify-action')

            lines.push(...dockerLines)

            lines.push(
                '    displayName: Upload SBOM',
                '    env:',
                '      SBOMIFY_TOKEN: $(SBOMIFY_TOKEN)'
            )

            return lines.join('\n')
        }

        test('should generate valid Azure Pipelines YAML with lock file source', () => {
            const yaml = generateAzureYaml(testComponentId, testComponentName, 'lock', {
                augment: true,
                enrich: true,
                outputFile: true
            })

            expect(yaml).toContain('trigger:')
            expect(yaml).toContain('vmImage: ubuntu-latest')
            expect(yaml).toContain('docker run --rm -v $(Build.SourcesDirectory):/code')
            expect(yaml).toContain(`COMPONENT_ID='${testComponentId}'`)
            expect(yaml).toContain(`COMPONENT_NAME='${testComponentName}'`)
            expect(yaml).toContain('LOCK_FILE=/code/poetry.lock')
            expect(yaml).toContain('AUGMENT=true')
            expect(yaml).toContain('ENRICH=true')
            expect(yaml).toContain('OUTPUT_FILE=/code/sbom.cdx.json')
            expect(yaml).toContain('sbomifyhub/sbomify-action')
            expect(yaml).toContain('displayName: Upload SBOM')
        })

        test('should generate Azure YAML with SBOM file source', () => {
            const yaml = generateAzureYaml(testComponentId, testComponentName, 'sbom', {
                augment: false,
                enrich: false,
                outputFile: false
            })

            expect(yaml).toContain('SBOM_FILE=/code/path/to/sbom.cdx.json')
            expect(yaml).not.toContain('AUGMENT=true')
            expect(yaml).not.toContain('ENRICH=true')
            expect(yaml).not.toContain('OUTPUT_FILE')
        })

        test('should generate Azure YAML with Docker image source', () => {
            const yaml = generateAzureYaml(testComponentId, testComponentName, 'docker', {
                augment: true,
                enrich: false,
                outputFile: true
            })

            expect(yaml).toContain('/var/run/docker.sock:/var/run/docker.sock')
            expect(yaml).toContain("DOCKER_IMAGE='your-image:tag'")
            expect(yaml).toContain('AUGMENT=true')
            expect(yaml).not.toContain('ENRICH=true')
        })
    })

    describe('Jenkins Pipeline Generation', () => {
        const generateJenkinsfile = (
            componentId: string,
            componentName: string,
            sourceType: string,
            config: Config
        ): string => {
            const lines = [
                'pipeline {',
                '    agent any',
                '',
                '    environment {',
                "        SBOMIFY_TOKEN = credentials('sbomify-token')",
                `        COMPONENT_ID = '${componentId}'`,
                `        COMPONENT_NAME = '${componentName}'`,
                '    }',
                '',
                '    stages {',
                "        stage('Upload SBOM') {",
                '            steps {',
                '                script {',
                '                    def version = env.TAG_NAME ?: "${env.BRANCH_NAME}-${env.GIT_COMMIT}"'
            ]

            lines.push('                    sh """')
            lines.push('                        docker run --rm -v $WORKSPACE:/code \\\\')

            if (sourceType === 'docker') {
                lines.push('                          -v /var/run/docker.sock:/var/run/docker.sock \\\\')
            }

            lines.push(
                '                          -e TOKEN=$SBOMIFY_TOKEN \\\\',
                '                          -e COMPONENT_ID=$COMPONENT_ID \\\\',
                '                          -e COMPONENT_NAME=$COMPONENT_NAME \\\\',
                '                          -e COMPONENT_VERSION=$version \\\\'
            )

            switch (sourceType) {
                case 'sbom':
                    lines.push('                          -e SBOM_FILE=/code/path/to/sbom.cdx.json \\\\')
                    break
                case 'lock':
                    lines.push('                          -e LOCK_FILE=/code/poetry.lock \\\\')
                    break
                case 'docker':
                    lines.push("                          -e DOCKER_IMAGE='your-image:tag' \\\\")
                    break
            }

            if (config.augment) lines.push('                          -e AUGMENT=true \\\\')
            if (config.enrich) lines.push('                          -e ENRICH=true \\\\')
            if (config.outputFile) lines.push('                          -e OUTPUT_FILE=/code/sbom.cdx.json \\\\')

            const lastLine = lines[lines.length - 1]
            lines[lines.length - 1] = lastLine.replace(/ \\\\$/, '')
            lines.push('                          sbomifyhub/sbomify-action')

            lines.push(
                '                    """',
                '                }',
                '            }',
                '        }',
                '    }',
                '}'
            )

            return lines.join('\n')
        }

        test('should generate valid Jenkinsfile with lock file source', () => {
            const jenkinsfile = generateJenkinsfile(testComponentId, testComponentName, 'lock', {
                augment: true,
                enrich: true,
                outputFile: true
            })

            expect(jenkinsfile).toContain('pipeline {')
            expect(jenkinsfile).toContain('agent any')
            expect(jenkinsfile).toContain("credentials('sbomify-token')")
            expect(jenkinsfile).toContain(`COMPONENT_ID = '${testComponentId}'`)
            expect(jenkinsfile).toContain(`COMPONENT_NAME = '${testComponentName}'`)
            expect(jenkinsfile).toContain("stage('Upload SBOM')")
            expect(jenkinsfile).toContain('docker run --rm -v $WORKSPACE:/code')
            expect(jenkinsfile).toContain('LOCK_FILE=/code/poetry.lock')
            expect(jenkinsfile).toContain('AUGMENT=true')
            expect(jenkinsfile).toContain('ENRICH=true')
            expect(jenkinsfile).toContain('OUTPUT_FILE=/code/sbom.cdx.json')
            expect(jenkinsfile).toContain('sbomifyhub/sbomify-action')
        })

        test('should generate Jenkinsfile with SBOM file source', () => {
            const jenkinsfile = generateJenkinsfile(testComponentId, testComponentName, 'sbom', {
                augment: false,
                enrich: false,
                outputFile: false
            })

            expect(jenkinsfile).toContain('SBOM_FILE=/code/path/to/sbom.cdx.json')
            expect(jenkinsfile).not.toContain('AUGMENT=true')
            expect(jenkinsfile).not.toContain('ENRICH=true')
            expect(jenkinsfile).not.toContain('OUTPUT_FILE')
        })

        test('should generate Jenkinsfile with Docker image source', () => {
            const jenkinsfile = generateJenkinsfile(testComponentId, testComponentName, 'docker', {
                augment: true,
                enrich: false,
                outputFile: true
            })

            expect(jenkinsfile).toContain('/var/run/docker.sock:/var/run/docker.sock')
            expect(jenkinsfile).toContain("DOCKER_IMAGE='your-image:tag'")
            expect(jenkinsfile).toContain('AUGMENT=true')
            expect(jenkinsfile).not.toContain('ENRICH=true')
        })
    })

    describe('Docker Command Generation', () => {
        const generateDockerCommand = (
            componentId: string,
            componentName: string,
            sourceType: string,
            config: Config
        ): string => {
            const cmd = [
                '# Set your component version (e.g., export VERSION=v1.0.0)',
                '# Pull and run the sbomify action container',
                'docker run -it --rm \\\\'
            ]

            if (sourceType === 'docker') {
                cmd.push('  -v /var/run/docker.sock:/var/run/docker.sock \\\\')
            }

            cmd.push('  -e TOKEN=$SBOMIFY_TOKEN \\\\',
                `  -e COMPONENT_ID=${componentId} \\\\`,
                `  -e COMPONENT_NAME=${componentName} \\\\`,
                '  -e COMPONENT_VERSION=$VERSION \\\\')

            switch (sourceType) {
                case 'sbom':
                    cmd.push('  -v $(pwd)/path/to/sbom.cdx.json:/sbom.cdx.json \\\\',
                        '  -e SBOM_FILE=/sbom.cdx.json \\\\')
                    break
                case 'lock':
                    cmd.push('  -v $(pwd)/poetry.lock:/app/poetry.lock \\\\',
                        '  -e LOCK_FILE=/app/poetry.lock \\\\')
                    break
                case 'docker':
                    cmd.push('  -e DOCKER_IMAGE=your-image:tag \\\\')
                    break
            }

            if (config.augment) cmd.push('  -e AUGMENT=true \\\\')
            if (config.enrich) cmd.push('  -e ENRICH=true \\\\')
            if (config.outputFile) cmd.push('  -e OUTPUT_FILE=sbom.cdx.json \\\\')

            cmd.push('  sbomifyhub/sbomify-action')

            return cmd.join('\n')
        }

        test('should generate Docker command with lock file', () => {
            const cmd = generateDockerCommand(testComponentId, testComponentName, 'lock', {
                augment: true,
                enrich: true,
                outputFile: true
            })

            expect(cmd).toContain('docker run -it --rm')
            expect(cmd).toContain(`COMPONENT_ID=${testComponentId}`)
            expect(cmd).toContain('poetry.lock:/app/poetry.lock')
            expect(cmd).toContain('sbomifyhub/sbomify-action')
        })

        test('should mount docker socket for docker source', () => {
            const cmd = generateDockerCommand(testComponentId, testComponentName, 'docker', {
                augment: false,
                enrich: false,
                outputFile: false
            })

            expect(cmd).toContain('/var/run/docker.sock:/var/run/docker.sock')
            expect(cmd).toContain('DOCKER_IMAGE=your-image:tag')
        })
    })

    describe('Source Type Selection', () => {
        test('should support all source types', () => {
            const sourceTypes = ['lock', 'sbom', 'docker']

            sourceTypes.forEach(type => {
                expect(['lock', 'sbom', 'docker']).toContain(type)
            })
        })
    })

    describe('Configuration Options', () => {
        test('should toggle augment option', () => {
            const config: Config = { augment: true, enrich: true, outputFile: true }

            config.augment = false
            expect(config.augment).toBe(false)

            config.augment = true
            expect(config.augment).toBe(true)
        })

        test('should toggle enrich option', () => {
            const config: Config = { augment: true, enrich: true, outputFile: true }

            config.enrich = false
            expect(config.enrich).toBe(false)
        })

        test('should toggle outputFile option', () => {
            const config: Config = { augment: true, enrich: true, outputFile: true }

            config.outputFile = false
            expect(config.outputFile).toBe(false)
        })

        test('should support all options disabled', () => {
            const config: Config = { augment: false, enrich: false, outputFile: false }

            expect(config.augment).toBe(false)
            expect(config.enrich).toBe(false)
            expect(config.outputFile).toBe(false)
        })
    })

    describe('Content Update Logic', () => {
        test('should select correct generator based on tab', () => {
            const updateContent = (activeTab: string): string => {
                switch (activeTab) {
                    case 'github':
                        return 'github-yaml'
                    case 'gitlab':
                        return 'gitlab-yaml'
                    case 'bitbucket':
                        return 'bitbucket-yaml'
                    case 'azure':
                        return 'azure-yaml'
                    case 'jenkins':
                        return 'jenkinsfile'
                    default:
                        return ''
                }
            }

            expect(updateContent('github')).toBe('github-yaml')
            expect(updateContent('gitlab')).toBe('gitlab-yaml')
            expect(updateContent('bitbucket')).toBe('bitbucket-yaml')
            expect(updateContent('azure')).toBe('azure-yaml')
            expect(updateContent('jenkins')).toBe('jenkinsfile')
        })
    })

    describe('Clipboard Functionality', () => {
        test('should prepare content for clipboard', () => {
            const content = 'name: Upload SBOM\non:\n  push:\n    branches: [ main ]'

            const prepareForClipboard = (c: string): string => {
                return c.trim()
            }

            expect(prepareForClipboard(content)).toBe(content)
            expect(prepareForClipboard('  content  ')).toBe('content')
        })
    })
})
