/**
 * Composable for centralized URL generation patterns used across the application
 */
export function useUrlGeneration(isPublicView = false) {

  /**
   * Generate URL for a document detail page
   */
  const getDocumentDetailUrl = (documentId: string, componentId?: string): string => {
    // For the new URL structure, we need the component ID
    if (componentId) {
      if (isPublicView) {
        return `/public/component/${componentId}/detailed/`
      }
      return `/component/${componentId}/detailed/`
    }

    // Fallback to document URLs if component ID not available
    if (isPublicView) {
      return `/public/document/${documentId}/`
    }
    return `/document/${documentId}/`
  }

  /**
   * Generate URL for document download
   */
  const getDocumentDownloadUrl = (documentId: string): string => {
    return `/api/v1/documents/${documentId}/download`
  }

  /**
   * Generate URL for document releases page
   */
  const getDocumentReleasesUrl = (documentId: string): string => {
    if (isPublicView) {
      return `/public/document/${documentId}/releases/`
    }
    return `/document/${documentId}/releases/`
  }

  /**
   * Generate URL for SBOM detail page
   */
  const getSbomDetailUrl = (sbomId: string, componentId?: string): string => {
    // For the new URL structure, we need the component ID
    if (componentId) {
      if (isPublicView) {
        return `/public/component/${componentId}/detailed/`
      }
      return `/component/${componentId}/detailed/`
    }

    // Fallback to old URLs if component ID not available
    if (isPublicView) {
      return `/public/sbom/${sbomId}/`
    }
    return `/sbom/${sbomId}/`
  }

  /**
   * Generate URL for SBOM download
   */
  const getSbomDownloadUrl = (sbomId: string): string => {
    return `/api/v1/sboms/${sbomId}/download`
  }

  /**
   * Generate URL for SBOM releases page
   */
  const getSbomReleasesUrl = (sbomId: string): string => {
    return `/sbom/${sbomId}/releases/`
  }

  /**
   * Generate URL for product page
   */
  const getProductUrl = (productId: string): string => {
    if (isPublicView) {
      return `/public/product/${productId}/`
    }
    return `/product/${productId}/`
  }

  /**
   * Generate URL for project page
   */
  const getProjectUrl = (projectId: string): string => {
    if (isPublicView) {
      return `/public/project/${projectId}/`
    }
    return `/project/${projectId}/`
  }

  /**
   * Generate URL for component page
   */
  const getComponentUrl = (componentId: string): string => {
    if (isPublicView) {
      return `/public/component/${componentId}/`
    }
    return `/component/${componentId}/`
  }

  /**
   * Generate URL for release page
   */
  const getReleaseUrl = (productId: string, releaseId: string): string => {
    if (isPublicView) {
      return `/public/product/${productId}/release/${releaseId}/`
    }
    return `/product/${productId}/release/${releaseId}/`
  }

  return {
    getDocumentDetailUrl,
    getDocumentDownloadUrl,
    getDocumentReleasesUrl,
    getSbomDetailUrl,
    getSbomDownloadUrl,
    getSbomReleasesUrl,
    getProductUrl,
    getProjectUrl,
    getComponentUrl,
    getReleaseUrl
  }
}