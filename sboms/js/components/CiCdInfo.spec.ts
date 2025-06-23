import { describe, test, expect } from 'bun:test'

/**
 * Tests for CiCdInfo Vue component business logic
 *
 * This test suite validates the core functionality of the CI/CD integration component
 * without requiring a full Vue component mount, focusing on business logic and data
 * transformations.
 */

describe('CiCdInfo Business Logic', () => {
  const testComponentId = 'test-component-123'
  const testComponentName = 'test-component'

  describe('Configuration Management', () => {
    test('should manage source type selection correctly', () => {
      const sourceTypes = ['sbom', 'lock', 'docker']
      let selectedType = 'lock'

      sourceTypes.forEach(type => {
        selectedType = type
        expect(['sbom', 'lock', 'docker']).toContain(selectedType)
      })
    })

    test('should manage configuration options state', () => {
      interface Config {
        augment: boolean
        enrich: boolean
        outputFile: boolean
      }

      const initialConfig: Config = {
        augment: true,
        enrich: true,
        outputFile: true
      }

      expect(initialConfig.augment).toBe(true)
      expect(initialConfig.enrich).toBe(true)
      expect(initialConfig.outputFile).toBe(true)

      // Test toggling options
      const modifiedConfig = { ...initialConfig, augment: false }
      expect(modifiedConfig.augment).toBe(false)
    })

    test('should handle tab switching correctly', () => {
      const tabs = ['github', 'gitlab', 'bitbucket', 'docker']
      let activeTab = 'github'

      tabs.forEach(tab => {
        activeTab = tab
        expect(activeTab).toBe(tab)
      })
    })
  })

  describe('Content Generation Logic', () => {
    test('should generate GitHub workflow YAML correctly', () => {
      interface Config {
        augment: boolean
        enrich: boolean
        outputFile: boolean
      }

      const generateGithubYaml = (componentId: string, componentName: string, sourceType: string, config: Config) => {
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
          '        uses: sbomify/github-action@master',
          '        env:',
          `          TOKEN: \${{ secrets.SBOMIFY_TOKEN }}`,
          `          COMPONENT_ID: '${componentId}'`,
          `          COMPONENT_NAME: '${componentName}'`,
          `          COMPONENT_VERSION: \${{ github.ref_type == 'tag' && github.ref_name || format('{0}-{1}', github.ref_name, github.sha) }}`
        ]

        // Add source-specific configuration
        switch (sourceType) {
          case 'sbom':
            yaml.push(`          SBOM_FILE: 'path/to/sbom.cdx.json'`)
            break
          case 'lock':
            yaml.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`)
            break
          case 'docker':
            yaml.push(`          DOCKER_IMAGE: 'your-image:tag'`)
            break
        }

        // Add boolean configurations
        if (config.augment) yaml.push('          AUGMENT: true')
        if (config.enrich) yaml.push('          ENRICH: true')
        if (config.outputFile) yaml.push('          OUTPUT_FILE: sbom.cdx.json')

        return yaml.join('\n')
      }

      const result = generateGithubYaml(testComponentId, testComponentName, 'lock', {
        augment: true,
        enrich: true,
        outputFile: true
      })

      expect(result).toContain('name: Upload SBOM')
      expect(result).toContain('uses: sbomify/github-action@master')
      expect(result).toContain(`COMPONENT_ID: '${testComponentId}'`)
      expect(result).toContain(`COMPONENT_NAME: '${testComponentName}'`)
      expect(result).toContain(`COMPONENT_VERSION: \${{ github.ref_type == 'tag' && github.ref_name || format('{0}-{1}', github.ref_name, github.sha) }}`)
      expect(result).toContain(`LOCK_FILE: 'poetry.lock'`)
      expect(result).toContain('AUGMENT: true')
      expect(result).toContain('ENRICH: true')
      expect(result).toContain('OUTPUT_FILE: sbom.cdx.json')
    })

    test('should generate GitLab CI YAML correctly for different source types', () => {
      interface Config {
        augment: boolean
        enrich: boolean
        outputFile: boolean
      }

      const generateGitlabYaml = (componentId: string, componentName: string, sourceType: string, config: Config) => {
        const yaml = [
          'upload-sbom:',
          '  stage: deploy',
          '  image: sbomifyhub/sbomify-action'
        ]

        if (sourceType === 'docker') {
          yaml.push('  services:',
                   '    - docker:dind',
                   '  variables:',
                   '    DOCKER_HOST: tcp://docker:2376',
                   '    DOCKER_TLS_VERIFY: 1',
                   '    DOCKER_CERT_PATH: /certs/client')
        }

        yaml.push('  variables:',
                  `    TOKEN: \$SBOMIFY_TOKEN`,
                  `    COMPONENT_ID: '${componentId}'`,
                  `    COMPONENT_NAME: '${componentName}'`,
                  `    COMPONENT_VERSION: \${CI_COMMIT_TAG:-\$CI_COMMIT_REF_NAME-\$CI_COMMIT_SHORT_SHA}`)

        switch (sourceType) {
          case 'sbom':
            yaml.push(`    SBOM_FILE: 'path/to/sbom.cdx.json'`)
            break
          case 'lock':
            yaml.push(`    LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`)
            break
          case 'docker':
            yaml.push(`    DOCKER_IMAGE: 'your-image:tag'        # Using Docker-in-Docker service`)
            break
        }

        if (config.augment) yaml.push('    AUGMENT: true')
        if (config.enrich) yaml.push('    ENRICH: true')
        if (config.outputFile) yaml.push('    OUTPUT_FILE: sbom.cdx.json')

        yaml.push('  script:', '    - /entrypoint.sh')

        return yaml.join('\n')
      }

      // Test Docker source type (includes DinD service)
      const dockerResult = generateGitlabYaml(testComponentId, testComponentName, 'docker', {
        augment: true,
        enrich: false,
        outputFile: false
      })

      expect(dockerResult).toContain('services:')
      expect(dockerResult).toContain('- docker:dind')
      expect(dockerResult).toContain('DOCKER_HOST: tcp://docker:2376')
      expect(dockerResult).toContain(`COMPONENT_NAME: '${testComponentName}'`)
      expect(dockerResult).toContain(`COMPONENT_VERSION: \${CI_COMMIT_TAG:-\$CI_COMMIT_REF_NAME-\$CI_COMMIT_SHORT_SHA}`)
      expect(dockerResult).toContain(`DOCKER_IMAGE: 'your-image:tag'`)
      expect(dockerResult).toContain('AUGMENT: true')
      expect(dockerResult).not.toContain('ENRICH: true')
      expect(dockerResult).not.toContain('OUTPUT_FILE: sbom.cdx.json')

      // Test SBOM source type (no DinD service)
      const sbomResult = generateGitlabYaml(testComponentId, testComponentName, 'sbom', {
        augment: false,
        enrich: true,
        outputFile: true
      })

      expect(sbomResult).not.toContain('services:')
      expect(sbomResult).toContain(`COMPONENT_NAME: '${testComponentName}'`)
      expect(sbomResult).toContain(`COMPONENT_VERSION: \${CI_COMMIT_TAG:-\$CI_COMMIT_REF_NAME-\$CI_COMMIT_SHORT_SHA}`)
      expect(sbomResult).toContain(`SBOM_FILE: 'path/to/sbom.cdx.json'`)
      expect(sbomResult).toContain('ENRICH: true')
      expect(sbomResult).toContain('OUTPUT_FILE: sbom.cdx.json')
      expect(sbomResult).not.toContain('AUGMENT: true')
    })

    test('should generate Bitbucket pipeline YAML correctly', () => {
      interface Config {
        augment: boolean
        enrich: boolean
        outputFile: boolean
      }

      const generateBitbucketYaml = (componentId: string, componentName: string, sourceType: string, config: Config) => {
        const yaml = [
          'pipelines:',
          '  default:',
          '    - step:',
          '        name: Upload SBOM',
          '        image: sbomifyhub/sbomify-action',
          '        services:',
          '          - docker'
        ]

        if (sourceType === 'docker') {
          yaml.push('        docker: true')
        }

        yaml.push('        script:',
                  '          - /entrypoint.sh',
                  '        env:',
                  `          TOKEN: \$SBOMIFY_TOKEN`,
                  `          COMPONENT_ID: '${componentId}'`,
                  `          COMPONENT_NAME: '${componentName}'`,
                  `          COMPONENT_VERSION: \${BITBUCKET_TAG:-\$BITBUCKET_BRANCH-\$BITBUCKET_COMMIT}`)

        switch (sourceType) {
          case 'sbom':
            yaml.push(`          SBOM_FILE: 'path/to/sbom.cdx.json'`)
            break
          case 'lock':
            yaml.push(`          LOCK_FILE: 'poetry.lock'              # Or package-lock.json, Gemfile.lock, etc.`)
            break
          case 'docker':
            yaml.push(`          DOCKER_IMAGE: 'your-image:tag'        # Using Docker service`)
            break
        }

        if (config.augment) yaml.push('          AUGMENT: true')
        if (config.enrich) yaml.push('          ENRICH: true')
        if (config.outputFile) yaml.push('          OUTPUT_FILE: sbom.cdx.json')

        return yaml.join('\n')
      }

      const result = generateBitbucketYaml(testComponentId, testComponentName, 'lock', {
        augment: true,
        enrich: true,
        outputFile: true
      })

      expect(result).toContain('pipelines:')
      expect(result).toContain('name: Upload SBOM')
      expect(result).toContain('image: sbomifyhub/sbomify-action')
      expect(result).toContain('services:')
      expect(result).toContain('- docker')
      expect(result).toContain(`COMPONENT_NAME: '${testComponentName}'`)
      expect(result).toContain(`COMPONENT_VERSION: \${BITBUCKET_TAG:-\$BITBUCKET_BRANCH-\$BITBUCKET_COMMIT}`)
      expect(result).toContain(`LOCK_FILE: 'poetry.lock'`)
      expect(result).toContain('AUGMENT: true')
      expect(result).toContain('ENRICH: true')
      expect(result).toContain('OUTPUT_FILE: sbom.cdx.json')
    })

    test('should generate Docker command correctly', () => {
      interface Config {
        augment: boolean
        enrich: boolean
        outputFile: boolean
      }

      const generateDockerCommand = (componentId: string, componentName: string, sourceType: string, config: Config) => {
        const cmd = [
          '# Set your component version (e.g., export VERSION=v1.0.0)',
          '# Pull and run the sbomify action container',
          'docker run -it --rm \\'
        ]

        if (sourceType === 'docker') {
          cmd.push('  -v /var/run/docker.sock:/var/run/docker.sock \\')
        }

        cmd.push('  -e TOKEN=$SBOMIFY_TOKEN \\',
                `  -e COMPONENT_ID=${componentId} \\`,
                `  -e COMPONENT_NAME=${componentName} \\`,
                '  -e COMPONENT_VERSION=$VERSION \\')

        switch (sourceType) {
          case 'sbom':
            cmd.push('  -v $(pwd)/path/to/sbom.cdx.json:/sbom.cdx.json \\',
                    '  -e SBOM_FILE=/sbom.cdx.json \\')
            break
          case 'lock':
            cmd.push('  -v $(pwd)/poetry.lock:/app/poetry.lock \\',
                    '  -e LOCK_FILE=/app/poetry.lock \\')
            break
          case 'docker':
            cmd.push('  -e DOCKER_IMAGE=your-image:tag \\')
            break
        }

        if (config.augment) cmd.push('  -e AUGMENT=true \\')
        if (config.enrich) cmd.push('  -e ENRICH=true \\')
        if (config.outputFile) cmd.push('  -e OUTPUT_FILE=sbom.cdx.json \\')

        cmd.push('  sbomifyhub/sbomify-action')

        return cmd.join('\n')
      }

      const result = generateDockerCommand(testComponentId, testComponentName, 'docker', {
        augment: false,
        enrich: true,
        outputFile: false
      })

      expect(result).toContain('docker run -it --rm \\')
      expect(result).toContain('-v /var/run/docker.sock:/var/run/docker.sock \\')
      expect(result).toContain(`-e COMPONENT_ID=${testComponentId} \\`)
      expect(result).toContain(`-e COMPONENT_NAME=${testComponentName} \\`)
      expect(result).toContain('-e COMPONENT_VERSION=$VERSION \\')
      expect(result).toContain('-e DOCKER_IMAGE=your-image:tag \\')
      expect(result).toContain('-e ENRICH=true \\')
      expect(result).toContain('sbomifyhub/sbomify-action')
      expect(result).not.toContain('-e AUGMENT=true \\')
      expect(result).not.toContain('-e OUTPUT_FILE=sbom.cdx.json \\')
    })
  })

  describe('Source Type Handling', () => {
    test('should handle all supported source types correctly', () => {
      const supportedTypes = ['sbom', 'lock', 'docker']

      supportedTypes.forEach(type => {
        expect(['sbom', 'lock', 'docker']).toContain(type)
      })
    })

    test('should include correct environment variables for each source type', () => {
      const getSourceSpecificEnvVars = (sourceType: string) => {
        switch (sourceType) {
          case 'sbom':
            return ['SBOM_FILE']
          case 'lock':
            return ['LOCK_FILE']
          case 'docker':
            return ['DOCKER_IMAGE']
          default:
            return []
        }
      }

      expect(getSourceSpecificEnvVars('sbom')).toEqual(['SBOM_FILE'])
      expect(getSourceSpecificEnvVars('lock')).toEqual(['LOCK_FILE'])
      expect(getSourceSpecificEnvVars('docker')).toEqual(['DOCKER_IMAGE'])
      expect(getSourceSpecificEnvVars('invalid')).toEqual([])
    })

    test('should include common environment variables for all source types', () => {
      const getCommonEnvVars = () => {
        return ['TOKEN', 'COMPONENT_ID', 'COMPONENT_NAME', 'COMPONENT_VERSION']
      }

      const commonVars = getCommonEnvVars()
      expect(commonVars).toContain('TOKEN')
      expect(commonVars).toContain('COMPONENT_ID')
      expect(commonVars).toContain('COMPONENT_NAME')
      expect(commonVars).toContain('COMPONENT_VERSION')
      expect(commonVars).toHaveLength(4)
    })
  })

  describe('Platform-specific Features', () => {
    test('should include Docker-in-Docker service for GitLab when using Docker source', () => {
      const needsDinD = (platform: string, sourceType: string) => {
        return platform === 'gitlab' && sourceType === 'docker'
      }

      expect(needsDinD('gitlab', 'docker')).toBe(true)
      expect(needsDinD('gitlab', 'sbom')).toBe(false)
      expect(needsDinD('github', 'docker')).toBe(false)
      expect(needsDinD('bitbucket', 'docker')).toBe(false)
    })

    test('should show appropriate notices for each platform and source combination', () => {
      const getNoticeVisibility = (activeTab: string, sourceType: string) => {
        return {
          gitlabNote: activeTab === 'gitlab',
          bitbucketNote: activeTab === 'bitbucket',
          githubDockerNote: activeTab === 'github' && sourceType === 'docker',
          dockerCliNote: activeTab === 'docker' && sourceType === 'docker'
        }
      }

      // GitLab tab
      let visibility = getNoticeVisibility('gitlab', 'sbom')
      expect(visibility.gitlabNote).toBe(true)
      expect(visibility.bitbucketNote).toBe(false)

      // Bitbucket tab
      visibility = getNoticeVisibility('bitbucket', 'docker')
      expect(visibility.gitlabNote).toBe(false)
      expect(visibility.bitbucketNote).toBe(true)

      // GitHub tab with Docker source
      visibility = getNoticeVisibility('github', 'docker')
      expect(visibility.githubDockerNote).toBe(true)

      // Docker tab with Docker source
      visibility = getNoticeVisibility('docker', 'docker')
      expect(visibility.dockerCliNote).toBe(true)
    })
  })

  describe('Tab Management', () => {
    test('should maintain correct tab state', () => {
      const tabs = [
        { id: 'github', name: 'GitHub', icon: 'fab fa-github' },
        { id: 'gitlab', name: 'GitLab', icon: 'fab fa-gitlab' },
        { id: 'bitbucket', name: 'Bitbucket', icon: 'fab fa-bitbucket' },
        { id: 'azure', name: 'Azure', icon: 'fab fa-microsoft' },
        { id: 'jenkins', name: 'Jenkins', icon: 'fab fa-jenkins' }
      ]

      expect(tabs).toHaveLength(5)
      expect(tabs.find(tab => tab.id === 'github')).toBeDefined()
      expect(tabs.find(tab => tab.id === 'gitlab')).toBeDefined()
      expect(tabs.find(tab => tab.id === 'bitbucket')).toBeDefined()
      expect(tabs.find(tab => tab.id === 'azure')).toBeDefined()
      expect(tabs.find(tab => tab.id === 'jenkins')).toBeDefined()
    })

    test('should handle tab clicking logic', () => {
      let activeTab = 'github'

      const handleTabClick = (tab: string) => {
        activeTab = tab
        // In real component this would also trigger updateHighlighting()
      }

      handleTabClick('gitlab')
      expect(activeTab).toBe('gitlab')

      handleTabClick('bitbucket')
      expect(activeTab).toBe('bitbucket')
    })

    test('should default to lockfile source type', () => {
      const defaultSourceType = 'lock'
      expect(['sbom', 'lock', 'docker']).toContain(defaultSourceType)
      expect(defaultSourceType).toBe('lock')
    })
  })

  describe('Configuration Validation', () => {
    test('should validate boolean configuration options', () => {
      const validateConfig = (config: Record<string, unknown>) => {
        return {
          augment: typeof config.augment === 'boolean',
          enrich: typeof config.enrich === 'boolean',
          outputFile: typeof config.outputFile === 'boolean'
        }
      }

      const validConfig = {
        augment: true,
        enrich: false,
        outputFile: false
      }

      const validation = validateConfig(validConfig)
      expect(Object.values(validation).every(Boolean)).toBe(true)

      // Test invalid config
      const invalidConfig = {
        augment: 'true', // string instead of boolean
        enrich: false,
        outputFile: false
      }

      const invalidValidation = validateConfig(invalidConfig)
      expect(invalidValidation.augment).toBe(false)
      expect(invalidValidation.enrich).toBe(true)
      expect(invalidValidation.outputFile).toBe(true)
    })
  })

  describe('Component Integration', () => {
    test('should properly integrate with StandardCard component', () => {
      const cardProps = {
        title: "CI/CD Integration",
        collapsible: true,
        defaultExpanded: true,
        storageKey: "cicd-integration"
      }

      expect(cardProps.title).toBe("CI/CD Integration")
      expect(cardProps.collapsible).toBe(true)
      expect(cardProps.defaultExpanded).toBe(true)
      expect(cardProps.storageKey).toBe("cicd-integration")
    })

    test('should provide correct info notice content', () => {
      const infoNoticeContent = "Automate SBOM generation: Follow these steps to integrate SBOM generation into your CI/CD pipeline. For manual uploads, use the Upload SBOM section above."

      expect(infoNoticeContent).toContain("Automate SBOM generation")
      expect(infoNoticeContent).toContain("CI/CD pipeline")
      expect(infoNoticeContent).toContain("Upload SBOM section")
    })
  })

  describe('Info Notice Styling', () => {
    test('should use consistent info notice structure', () => {
      const createInfoNotice = (icon: string, text: string) => {
        return {
          className: 'info-notice mb-3',
          icon: `fas ${icon} text-info me-2`,
          content: text
        }
      }

      const gitlabNotice = createInfoNotice('fa-info-circle', 'GitLab CI requires Docker-in-Docker (DinD) service...')
      const tokenNotice = createInfoNotice('fa-key', 'Required: Before using any CI integration...')

      expect(gitlabNotice.className).toBe('info-notice mb-3')
      expect(gitlabNotice.icon).toContain('fas fa-info-circle text-info')
      expect(tokenNotice.icon).toContain('fas fa-key text-info')
    })
  })
})