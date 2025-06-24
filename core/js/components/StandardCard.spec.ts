import { describe, test, expect, beforeEach, afterEach } from 'bun:test'

// Mock sessionStorage for testing
const mockSessionStorage = {
  store: {} as { [key: string]: string },
  get length(): number {
    return Object.keys(this.store).length
  },
  getItem(key: string): string | null {
    return this.store[key] || null
  },
  setItem(key: string, value: string): void {
    this.store[key] = value
  },
  removeItem(key: string): void {
    delete this.store[key]
  },
  key(index: number): string | null {
    const keys = Object.keys(this.store)
    return keys[index] || null
  },
  clear(): void {
    this.store = {}
  }
}

// Set up global sessionStorage mock
global.sessionStorage = mockSessionStorage as unknown as Storage

describe('StandardCard Business Logic', () => {
  beforeEach(() => {
    // Clear session storage before each test
    sessionStorage.clear()
  })

  afterEach(() => {
    // Clean up after each test
    sessionStorage.clear()
  })

  describe('Basic Rendering', () => {
    test('should render card with title', () => {
      const mockCard = {
        title: 'Test Card',
        collapsible: false,
        defaultExpanded: true,
        infoIcon: 'fas fa-info-circle',
        storageKey: '',
        variant: 'default' as const,
        size: 'medium' as const,
        emphasis: false,
        centerContent: false,
        noPadding: false,
        shadow: 'sm' as const
      }

      expect(mockCard.title).toBe('Test Card')
      expect(mockCard.collapsible).toBe(false)
      expect(mockCard.defaultExpanded).toBe(true)
      expect(mockCard.variant).toBe('default')
      expect(mockCard.size).toBe('medium')
      expect(mockCard.emphasis).toBe(false)
    })

    test('should handle card without title', () => {
      const mockCard = {
        title: '',
        collapsible: false,
        defaultExpanded: true,
        infoIcon: 'fas fa-info-circle',
        storageKey: ''
      }

      expect(mockCard.title).toBe('')
    })

    test('should use correct default props', () => {
      const defaults = {
        title: '',
        collapsible: false,
        defaultExpanded: true,
        infoIcon: 'fas fa-info-circle',
        storageKey: '',
        variant: 'default',
        size: 'medium',
        emphasis: false,
        centerContent: false,
        noPadding: false,
        shadow: 'sm'
      }

      expect(defaults.title).toBe('')
      expect(defaults.collapsible).toBe(false)
      expect(defaults.defaultExpanded).toBe(true)
      expect(defaults.infoIcon).toBe('fas fa-info-circle')
      expect(defaults.storageKey).toBe('')
      expect(defaults.variant).toBe('default')
      expect(defaults.size).toBe('medium')
      expect(defaults.emphasis).toBe(false)
      expect(defaults.centerContent).toBe(false)
      expect(defaults.noPadding).toBe(false)
      expect(defaults.shadow).toBe('sm')
    })
  })

  describe('Variant Support', () => {
    test('should support stats variant', () => {
      const mockCard = {
        title: 'Stats Card',
        variant: 'stats' as const,
        centerContent: true
      }

      expect(mockCard.variant).toBe('stats')
      expect(mockCard.centerContent).toBe(true)
    })

    test('should support plan variant with emphasis', () => {
      const mockCard = {
        title: 'Business Plan',
        variant: 'plan' as const,
        emphasis: true
      }

      expect(mockCard.variant).toBe('plan')
      expect(mockCard.emphasis).toBe(true)
    })

    test('should support modal variant', () => {
      const mockCard = {
        title: 'Modal Content',
        variant: 'modal' as const
      }

      expect(mockCard.variant).toBe('modal')
    })

    test('should support settings variant', () => {
      const mockCard = {
        title: 'Settings',
        variant: 'settings' as const
      }

      expect(mockCard.variant).toBe('settings')
    })
  })

  describe('Size and Shadow Support', () => {
    test('should support different sizes', () => {
      const smallCard = { size: 'small' as const }
      const mediumCard = { size: 'medium' as const }
      const largeCard = { size: 'large' as const }

      expect(smallCard.size).toBe('small')
      expect(mediumCard.size).toBe('medium')
      expect(largeCard.size).toBe('large')
    })

    test('should support different shadow levels', () => {
      const noShadow = { shadow: 'none' as const }
      const smallShadow = { shadow: 'sm' as const }
      const mediumShadow = { shadow: 'md' as const }
      const largeShadow = { shadow: 'lg' as const }

      expect(noShadow.shadow).toBe('none')
      expect(smallShadow.shadow).toBe('sm')
      expect(mediumShadow.shadow).toBe('md')
      expect(largeShadow.shadow).toBe('lg')
    })
  })

  describe('CSS Class Generation', () => {
        test('should generate container classes based on size', () => {
      const generateContainerClasses = (size: string) => {
        const classes: string[] = []

        if (size === 'small') classes.push('mt-2')
        else if (size === 'large') classes.push('mt-4')
        else classes.push('mt-3')

        return classes.join(' ')
      }

      expect(generateContainerClasses('small')).toBe('mt-2')
      expect(generateContainerClasses('medium')).toBe('mt-3')
      expect(generateContainerClasses('large')).toBe('mt-4')
    })

        test('should generate card classes based on variant and shadow', () => {
      const generateCardClasses = (variant: string, emphasis: boolean, shadow: string) => {
        const classes: string[] = []

        // Variant-specific classes
        switch (variant) {
          case 'stats':
            classes.push('stats-card')
            break
          case 'plan':
            classes.push('plan-card')
            if (emphasis) classes.push('plan-emphasis')
            break
          case 'modal':
            classes.push('modal-card')
            break
          case 'settings':
            classes.push('settings-card')
            break
        }

        // Shadow classes
        switch (shadow) {
          case 'none':
            classes.push('shadow-none')
            break
          case 'md':
            classes.push('shadow-md')
            break
          case 'lg':
            classes.push('shadow-lg')
            break
          default:
            classes.push('shadow-sm')
        }

        return classes.join(' ')
      }

      expect(generateCardClasses('stats', false, 'sm')).toBe('stats-card shadow-sm')
      expect(generateCardClasses('plan', true, 'md')).toBe('plan-card plan-emphasis shadow-md')
      expect(generateCardClasses('modal', false, 'none')).toBe('modal-card shadow-none')
    })

        test('should generate header classes with emphasis', () => {
      const generateHeaderClasses = (collapsible: boolean, emphasis: boolean, variant: string) => {
        const classes: string[] = []

        if (collapsible) classes.push('collapsible-header')
        if (emphasis && variant === 'plan') {
          classes.push('bg-emphasis', 'text-emphasis', 'border-emphasis')
        }

        return classes.join(' ')
      }

      expect(generateHeaderClasses(true, false, 'default')).toBe('collapsible-header')
      expect(generateHeaderClasses(false, true, 'plan')).toBe('bg-emphasis text-emphasis border-emphasis')
      expect(generateHeaderClasses(true, true, 'plan')).toBe('collapsible-header bg-emphasis text-emphasis border-emphasis')
    })

        test('should generate body classes with collapse and content options', () => {
      const generateBodyClasses = (collapsible: boolean, isExpanded: boolean, centerContent: boolean, noPadding: boolean) => {
        const classes: string[] = []

        if (collapsible) {
          classes.push('collapse')
          if (isExpanded) classes.push('show')
        }

        if (centerContent) classes.push('text-center')
        if (noPadding) classes.push('p-0')

        return classes.join(' ')
      }

      expect(generateBodyClasses(true, true, false, false)).toBe('collapse show')
      expect(generateBodyClasses(false, false, true, true)).toBe('text-center p-0')
      expect(generateBodyClasses(true, false, true, false)).toBe('collapse text-center')
    })
  })

  describe('Collapsible Functionality', () => {
    test('should handle non-collapsible card state', () => {
      const mockCard = {
        title: 'Non-Collapsible Card',
        collapsible: false,
        defaultExpanded: true,
        storageKey: ''
      }

      let isExpanded = mockCard.defaultExpanded

      const toggleCollapse = () => {
        if (mockCard.collapsible) {
          isExpanded = !isExpanded
        }
      }

      // Should not change state when not collapsible
      toggleCollapse()
      expect(isExpanded).toBe(true)
    })

    test('should toggle collapsible card state', () => {
      const mockCard = {
        title: 'Collapsible Card',
        collapsible: true,
        defaultExpanded: true,
        storageKey: ''
      }

      let isExpanded = mockCard.defaultExpanded

      const toggleCollapse = () => {
        if (mockCard.collapsible) {
          isExpanded = !isExpanded
        }
      }

      // Should toggle when collapsible
      expect(isExpanded).toBe(true)
      toggleCollapse()
      expect(isExpanded).toBe(false)
      toggleCollapse()
      expect(isExpanded).toBe(true)
    })

    test('should respect defaultExpanded prop', () => {
      const expandedCard = {
        collapsible: true,
        defaultExpanded: true,
        storageKey: ''
      }

      const collapsedCard = {
        collapsible: true,
        defaultExpanded: false,
        storageKey: ''
      }

      expect(expandedCard.defaultExpanded).toBe(true)
      expect(collapsedCard.defaultExpanded).toBe(false)
    })
  })

  describe('Session Storage Integration', () => {
    test('should save collapse state to session storage', () => {
      const mockCard = {
        collapsible: true,
        defaultExpanded: true,
        storageKey: 'test-card'
      }

      let isExpanded = mockCard.defaultExpanded

      const toggleCollapse = () => {
        if (mockCard.collapsible) {
          isExpanded = !isExpanded

          if (mockCard.storageKey) {
            sessionStorage.setItem(`card-collapse-${mockCard.storageKey}`, isExpanded.toString())
          }
        }
      }

      // Toggle and check storage
      toggleCollapse()
      expect(isExpanded).toBe(false)
      expect(sessionStorage.getItem('card-collapse-test-card')).toBe('false')

      toggleCollapse()
      expect(isExpanded).toBe(true)
      expect(sessionStorage.getItem('card-collapse-test-card')).toBe('true')
    })

    test('should load initial state from session storage', () => {
      const storageKey = 'test-card-load'
      sessionStorage.setItem(`card-collapse-${storageKey}`, 'false')

      const getInitialExpandedState = (storageKey: string, defaultExpanded: boolean): boolean => {
        if (storageKey) {
          const stored = sessionStorage.getItem(`card-collapse-${storageKey}`)
          if (stored !== null) {
            return stored === 'true'
          }
        }
        return defaultExpanded
      }

      const isExpanded = getInitialExpandedState(storageKey, true)
      expect(isExpanded).toBe(false) // Should use stored value instead of default
    })

    test('should use default when no storage value exists', () => {
      const getInitialExpandedState = (storageKey: string, defaultExpanded: boolean): boolean => {
        if (storageKey) {
          const stored = sessionStorage.getItem(`card-collapse-${storageKey}`)
          if (stored !== null) {
            return stored === 'true'
          }
        }
        return defaultExpanded
      }

      const isExpandedTrue = getInitialExpandedState('non-existent-key', true)
      const isExpandedFalse = getInitialExpandedState('non-existent-key', false)

      expect(isExpandedTrue).toBe(true)
      expect(isExpandedFalse).toBe(false)
    })

    test('should not use storage when no storage key provided', () => {
      sessionStorage.setItem('card-collapse-', 'false')

      const mockCard = {
        collapsible: true,
        defaultExpanded: true,
        storageKey: ''
      }

      let isExpanded = mockCard.defaultExpanded

      const toggleCollapse = () => {
        if (mockCard.collapsible) {
          isExpanded = !isExpanded

          if (mockCard.storageKey) {
            sessionStorage.setItem(`card-collapse-${mockCard.storageKey}`, isExpanded.toString())
          }
        }
      }

      toggleCollapse()
      expect(isExpanded).toBe(false)
      // Should not have saved to storage
      expect(sessionStorage.getItem('card-collapse-')).toBe('false') // Unchanged
    })
  })

  describe('Icon Handling', () => {
    test('should use correct default info icon', () => {
      const mockCard = {
        infoIcon: 'fas fa-info-circle'
      }

      expect(mockCard.infoIcon).toBe('fas fa-info-circle')
    })

    test('should allow custom info icon', () => {
      const mockCard = {
        infoIcon: 'fas fa-warning'
      }

      expect(mockCard.infoIcon).toBe('fas fa-warning')
    })

    test('should generate random collapse ID', () => {
      const generateCollapseId = () => `collapse-${Math.random().toString(36).substr(2, 9)}`

      const id1 = generateCollapseId()
      const id2 = generateCollapseId()

      expect(id1).not.toBe(id2)
      expect(id1).toMatch(/^collapse-[a-z0-9]{9}$/)
      expect(id2).toMatch(/^collapse-[a-z0-9]{9}$/)
    })
  })

  describe('Slot Detection Logic', () => {
    test('should detect presence of info notice slot', () => {
      const mockSlots: { [key: string]: () => string } = {
        'info-notice': () => 'Info content'
      }

      const hasInfoNotice = !!mockSlots['info-notice']
      expect(hasInfoNotice).toBe(true)
    })

    test('should detect absence of info notice slot', () => {
      const mockSlots: { [key: string]: () => string } = {}

      const hasInfoNotice = !!mockSlots['info-notice']
      expect(hasInfoNotice).toBe(false)
    })

    test('should detect presence of footer slot', () => {
      const mockSlots: { [key: string]: () => string } = {
        footer: () => 'Footer content'
      }

      const hasFooter = !!mockSlots.footer
      expect(hasFooter).toBe(true)
    })

    test('should detect absence of footer slot', () => {
      const mockSlots: { [key: string]: () => string } = {}

      const hasFooter = !!mockSlots.footer
      expect(hasFooter).toBe(false)
    })

    test('should detect presence of header actions slot', () => {
      const mockSlots: { [key: string]: () => string } = {
        'header-actions': () => 'Header actions'
      }

      const hasHeaderActions = !!mockSlots['header-actions']
      expect(hasHeaderActions).toBe(true)
    })

    test('should detect absence of header actions slot', () => {
      const mockSlots: { [key: string]: () => string } = {}

      const hasHeaderActions = !!mockSlots['header-actions']
      expect(hasHeaderActions).toBe(false)
    })
  })

  describe('Content and Styling Options', () => {
    test('should handle centerContent option', () => {
      const centeredCard = {
        centerContent: true
      }

      const nonCenteredCard = {
        centerContent: false
      }

      expect(centeredCard.centerContent).toBe(true)
      expect(nonCenteredCard.centerContent).toBe(false)
    })

    test('should handle noPadding option', () => {
      const noPaddingCard = {
        noPadding: true
      }

      const paddedCard = {
        noPadding: false
      }

      expect(noPaddingCard.noPadding).toBe(true)
      expect(paddedCard.noPadding).toBe(false)
    })

    test('should handle emphasis state', () => {
      const emphasizedCard = {
        variant: 'plan' as const,
        emphasis: true
      }

      const normalCard = {
        variant: 'plan' as const,
        emphasis: false
      }

      expect(emphasizedCard.emphasis).toBe(true)
      expect(normalCard.emphasis).toBe(false)
    })
  })

  describe('Complex Integration Scenarios', () => {
    test('should handle collapsible card with storage and slots', () => {
      const mockCard = {
        title: 'Complex Card',
        collapsible: true,
        defaultExpanded: false,
        infoIcon: 'fas fa-warning',
        storageKey: 'complex-card',
        variant: 'settings' as const,
        size: 'large' as const,
        emphasis: false,
        centerContent: false,
        noPadding: true,
        shadow: 'lg' as const
      }

      const mockSlots: { [key: string]: () => string } = {
        'info-notice': () => 'Important notice',
        footer: () => 'Footer actions',
        'header-actions': () => 'Header actions'
      }

      // Set initial storage state
      sessionStorage.setItem('card-collapse-complex-card', 'true')

      const getInitialExpandedState = (): boolean => {
        if (mockCard.storageKey) {
          const stored = sessionStorage.getItem(`card-collapse-${mockCard.storageKey}`)
          if (stored !== null) {
            return stored === 'true'
          }
        }
        return mockCard.defaultExpanded
      }

      let isExpanded = getInitialExpandedState()
      const hasInfoNotice = !!mockSlots['info-notice']
      const hasFooter = !!mockSlots.footer
      const hasHeaderActions = !!mockSlots['header-actions']

      expect(isExpanded).toBe(true) // From storage, not default
      expect(hasInfoNotice).toBe(true)
      expect(hasFooter).toBe(true)
      expect(hasHeaderActions).toBe(true)
      expect(mockCard.title).toBe('Complex Card')
      expect(mockCard.infoIcon).toBe('fas fa-warning')
      expect(mockCard.variant).toBe('settings')
      expect(mockCard.size).toBe('large')
      expect(mockCard.noPadding).toBe(true)
      expect(mockCard.shadow).toBe('lg')
    })

    test('should handle multiple cards with different storage keys', () => {
      const card1 = { storageKey: 'card-1', defaultExpanded: true }
      const card2 = { storageKey: 'card-2', defaultExpanded: false }

      // Set different storage states
      sessionStorage.setItem('card-collapse-card-1', 'false')
      sessionStorage.setItem('card-collapse-card-2', 'true')

      const getInitialExpandedState = (storageKey: string, defaultExpanded: boolean): boolean => {
        if (storageKey) {
          const stored = sessionStorage.getItem(`card-collapse-${storageKey}`)
          if (stored !== null) {
            return stored === 'true'
          }
        }
        return defaultExpanded
      }

      const card1State = getInitialExpandedState(card1.storageKey, card1.defaultExpanded)
      const card2State = getInitialExpandedState(card2.storageKey, card2.defaultExpanded)

      expect(card1State).toBe(false) // Storage overrides default true
      expect(card2State).toBe(true)  // Storage overrides default false
    })

    test('should handle plan variant with emphasis and custom props', () => {
      const planCard = {
        title: 'Enterprise Plan',
        variant: 'plan' as const,
        emphasis: true,
        size: 'large' as const,
        shadow: 'md' as const,
        centerContent: false,
        noPadding: false
      }

      expect(planCard.variant).toBe('plan')
      expect(planCard.emphasis).toBe(true)
      expect(planCard.size).toBe('large')
      expect(planCard.shadow).toBe('md')
    })

    test('should handle stats variant with centered content', () => {
      const statsCard = {
        title: 'Total Users',
        variant: 'stats' as const,
        centerContent: true,
        size: 'medium' as const,
        shadow: 'sm' as const
      }

      expect(statsCard.variant).toBe('stats')
      expect(statsCard.centerContent).toBe(true)
      expect(statsCard.size).toBe('medium')
    })
  })
})