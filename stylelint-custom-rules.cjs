/**
 * Custom stylelint plugin for sbomify
 * Checks for hardcoded colors (hex, rgb, named) and enforces CSS variable usage
 */

const stylelint = require('stylelint');

const ruleName = 'sbomify/no-hardcoded-colors';
const messages = stylelint.utils.ruleMessages(ruleName, {
  hexColor: (color) => `Use CSS variables instead of hex colors. Found: ${color}. Use var(--variable-name) from tokens.css`,
  rgbColor: 'Use rgba(var(--variable-rgb), opacity) format instead of hardcoded rgb/rgba values',
  namedColor: (color) => `Use CSS variables instead of named colors. Found: ${color}. Use var(--white), var(--black), etc.`,
});

module.exports = stylelint.createPlugin(ruleName, (primary, secondaryOptions) => {
  return (root, result) => {
    const validOptions = stylelint.utils.validateOptions(
      result,
      ruleName,
      {
        actual: primary,
        possible: [true, false],
      },
      {
        actual: secondaryOptions,
        possible: {
          ignore: [isString, isArrayOfStrings],
        },
        optional: true,
      }
    );

    if (!validOptions || !primary) {
      return;
    }

    const ignoreFiles = secondaryOptions?.ignore || ['tokens.css'];
    const filePath = root.source?.input?.from || '';

    // Skip if file is in ignore list
    if (Array.isArray(ignoreFiles) && ignoreFiles.some(ignore => filePath.includes(ignore))) {
      return;
    }

    root.walkDecls((decl) => {
      const value = decl.value;
      const prop = decl.prop;

      // Skip if not a color-related property
      if (!prop.match(/^(color|background|border|box-shadow|text-shadow|outline|fill|stroke)/)) {
        return;
      }

      // Check for hex colors (except in selectors like #access-token)
      const hexPattern = /#[0-9a-fA-F]{3,6}(?![a-zA-Z0-9-])/g;
      const hexMatches = value.match(hexPattern);
      if (hexMatches) {
        // Allow #access-token (CSS selector, not a color)
        const filteredMatches = hexMatches.filter(match => match !== '#access-token');
        if (filteredMatches.length > 0) {
          stylelint.utils.report({
            message: messages.hexColor(filteredMatches[0]),
            node: decl,
            result,
            ruleName,
            word: filteredMatches[0],
          });
        }
      }

      // Check for rgb/rgba with numeric values (not var(--variable-rgb))
      const rgbPattern = /rgba?\(\s*[0-9]+\s*,\s*[0-9]+\s*,\s*[0-9]+/g;
      if (rgbPattern.test(value) && !value.includes('var(--')) {
        stylelint.utils.report({
          message: messages.rgbColor,
          node: decl,
          result,
          ruleName,
        });
      }
    });
  };
});

function isString(value) {
  return typeof value === 'string';
}

function isArrayOfStrings(value) {
  return Array.isArray(value) && value.every(isString);
}
