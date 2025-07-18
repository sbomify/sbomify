/**
 * Common utility functions used across components
 */
export function useCommonUtils() {
  /**
   * Truncate text to a maximum length with ellipsis
   */
  const truncateText = (text: string | null | undefined, maxLength: number): string => {
    if (!text) return ''
    if (text.length <= maxLength) return text
    return text.substring(0, maxLength) + '...'
  }

  /**
   * Format date string to localized date
   */
  const formatDate = (dateString: string): string => {
    try {
      const date = new Date(dateString)
      return date.toLocaleDateString()
    } catch {
      return dateString
    }
  }

  /**
   * Convert string boolean props to actual boolean
   */
  const normalizeBoolean = (value: boolean | string | undefined): boolean => {
    if (typeof value === 'string') {
      return value === 'true'
    }
    return value === true
  }

  /**
   * Generate CSRF token from cookies
   */
  const getCsrfToken = (): string => {
    const csrfCookie = document.cookie
      .split('; ')
      .find(row => row.startsWith('csrftoken='))
    return csrfCookie ? csrfCookie.split('=')[1] : ''
  }

  return {
    truncateText,
    formatDate,
    normalizeBoolean,
    getCsrfToken
  }
}