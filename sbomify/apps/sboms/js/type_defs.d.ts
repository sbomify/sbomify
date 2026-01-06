// Product/Project/Component related types moved to core/js/type_defs.d.ts
// AlertMessage type moved to core/js/type_defs.d.ts
// Import them from core if needed in sbom components

// Type declaration for license-expressions module
declare module 'license-expressions' {
  export interface LicenseToken {
    type: string
    value: string
  }

  export interface ParseResult {
    license?: string
    left?: ParseResult
    right?: ParseResult
    conjunction?: string
    exception?: string
  }

  export function parse(expression: string): ParseResult
  export function tokenize(expression: string): LicenseToken[]
}
