/**
 * stylelint Configuration for sbomify
 * 
 * Focus: Hardcoded color detection and essential best practices
 * Formatting: Handled by Prettier (via stylelint-config-prettier)
 */

module.exports = {
  extends: [
    'stylelint-config-prettier', // Disables all formatting rules, lets Prettier handle them
  ],
  plugins: ['./stylelint-custom-rules.cjs'],
  rules: {
    // ===== HARDCODED COLORS - STRICT ENFORCEMENT =====
    // Custom rule for hardcoded colors (hex, rgb, named)
    'sbomify/no-hardcoded-colors': true,
    
    // Prevent named colors
    'color-named': [
      'never',
      {
        message: 'Use CSS variables instead of named colors. Use var(--white), var(--black), etc. from tokens.css',
      },
    ],
    
    // ===== BEST PRACTICES =====
    // Prevent duplicate properties
    'declaration-block-no-duplicate-properties': true,
    
    // Prevent empty rules
    'block-no-empty': true,
    
    // Prevent duplicate selectors
    'no-duplicate-selectors': true,
    
    // Prevent empty sources
    'no-empty-source': true,
    
    // ===== VENDOR PREFIXES =====
    'value-no-vendor-prefix': [
      true,
      {
        ignoreValues: ['appearance', 'text-size-adjust'],
      },
    ],
    
    // ===== FUNCTION NAMING =====
    'function-name-case': 'lower',
    'function-calc-no-unspaced-operator': true,
    
    // ===== COMPLEXITY WARNINGS =====
    'selector-max-compound-selectors': 4,
    'selector-max-specificity': '0,4,0',
    
    // ===== FONT FAMILY =====
    'font-family-no-missing-generic-family-keyword': true,
    
    // ===== IMPORTANT (WARNING ONLY) =====
    'declaration-no-important': [
      true,
      {
        severity: 'warning',
      },
    ],
    
    // ===== AT-RULES (ALLOW TAILWIND) =====
    'at-rule-no-unknown': [
      true,
      {
        ignoreAtRules: ['tailwind', 'apply', 'layer', 'variants', 'responsive', 'screen'],
      },
    ],
    
    // ===== PROPERTIES =====
    'property-no-unknown': [
      true,
      {
        ignoreProperties: ['composes', 'compose-with'],
      },
    ],
    
    // ===== PSEUDO-CLASSES =====
    'selector-pseudo-class-no-unknown': [
      true,
      {
        ignorePseudoClasses: ['global', 'local'],
      },
    ],
    
    // ===== CSS VARIABLE NAMING =====
    'custom-property-pattern': '^[a-z][a-z0-9-]*$',
    
    // ===== ADDITIONAL BEST PRACTICES =====
    'declaration-block-no-redundant-longhand-properties': true,
    'shorthand-property-no-redundant-values': true,
    'no-descending-specificity': [
      true,
      {
        ignore: ['selectors-within-list'],
      },
    ],
    
    // ===== SYNTAX VALIDATION =====
    'color-no-invalid-hex': true,
    'function-no-unknown': true,
    'string-no-newline': true,
    'unit-no-unknown': true,
  },
  ignoreFiles: [
    '**/*.min.css',
    '**/bootstrap.min.css',
    '**/fontawesome.min.css',
    '**/node_modules/**',
    '**/staticfiles/**',
    '**/dist/**',
    '**/build/**',
  ],
  overrides: [
    {
      files: ['**/tokens.css'],
      rules: {
        // Allow hex colors in tokens.css (where they're defined)
        'sbomify/no-hardcoded-colors': null,
        'color-named': null,
      },
    },
    {
      files: ['**/pages.css'],
      rules: {
        // Allow #access-token selector (CSS ID selector, not a color)
        'sbomify/no-hardcoded-colors': [
          true,
          {
            ignore: ['#access-token'],
          },
        ],
      },
    },
  ],
};
