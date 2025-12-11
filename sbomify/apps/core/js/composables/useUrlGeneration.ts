/**
 * Composable for centralized URL generation patterns used across the application
 * 
 * On custom domains, slug-based URLs are used for cleaner, more readable URLs.
 * On the main app domain, ID-based URLs are used for compatibility.
 * 
 * @param isPublicView - Whether generating URLs for public pages
 * @param isCustomDomain - Whether the current request is on a custom domain
 */
export function useUrlGeneration(isPublicView = false, isCustomDomain = false) {

  /**
   * Generate URL for a document detail page
   * @param documentId - Document ID (used on main app domain)
   * @param componentId - Optional component ID for new URL structure
   * @param componentSlug - Optional component slug (used on custom domains)
   */
  const getDocumentDetailUrl = (documentId: string, componentId?: string, componentSlug?: string): string => {
    // For the new URL structure, we need the component ID/slug
    if (componentId) {
      if (isCustomDomain) {
        return `/component/${componentSlug || componentId}/detailed/`
      }
      if (isPublicView) {
        return `/public/component/${componentId}/detailed/`
      }
      return `/component/${componentId}/detailed/`
    }

    // Fallback to document URLs if component ID not available
    if (isCustomDomain) {
      return `/document/${documentId}/`
    }
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
    if (isCustomDomain) {
      return `/document/${documentId}/releases/`
    }
    if (isPublicView) {
      return `/public/document/${documentId}/releases/`
    }
    return `/document/${documentId}/releases/`
  }

  /**
   * Generate URL for SBOM detail page
   * @param sbomId - SBOM ID
   * @param componentId - Optional component ID for new URL structure
   * @param componentSlug - Optional component slug (used on custom domains)
   */
  const getSbomDetailUrl = (sbomId: string, componentId?: string, componentSlug?: string): string => {
    // For the new URL structure, we need the component ID/slug
    if (componentId) {
      if (isCustomDomain) {
        return `/component/${componentSlug || componentId}/detailed/`
      }
      if (isPublicView) {
        return `/public/component/${componentId}/detailed/`
      }
      return `/component/${componentId}/detailed/`
    }

    // Fallback to old URLs if component ID not available
    if (isCustomDomain) {
      return `/sbom/${sbomId}/`
    }
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
   * @param productId - Product ID (used on main app domain)
   * @param productSlug - Optional product slug (used on custom domains)
   */
  const getProductUrl = (productId: string, productSlug?: string): string => {
    if (isCustomDomain) {
      return `/product/${productSlug || productId}/`
    }
    if (isPublicView) {
      return `/public/product/${productId}/`
    }
    return `/product/${productId}/`
  }

  /**
   * Generate URL for project page
   * @param projectId - Project ID (used on main app domain)
   * @param projectSlug - Optional project slug (used on custom domains)
   */
  const getProjectUrl = (projectId: string, projectSlug?: string): string => {
    if (isCustomDomain) {
      return `/project/${projectSlug || projectId}/`
    }
    if (isPublicView) {
      return `/public/project/${projectId}/`
    }
    return `/project/${projectId}/`
  }

  /**
   * Generate URL for component page
   * @param componentId - Component ID (used on main app domain)
   * @param componentSlug - Optional component slug (used on custom domains)
   */
  const getComponentUrl = (componentId: string, componentSlug?: string): string => {
    if (isCustomDomain) {
      return `/component/${componentSlug || componentId}/`
    }
    if (isPublicView) {
      return `/public/component/${componentId}/`
    }
    return `/component/${componentId}/`
  }

  /**
   * Generate URL for release page
   * @param productId - Product ID (used on main app domain)
   * @param releaseId - Release ID (used on main app domain)
   * @param productSlug - Optional product slug (used on custom domains)
   * @param releaseSlug - Optional release slug (used on custom domains)
   */
  const getReleaseUrl = (productId: string, releaseId: string, productSlug?: string, releaseSlug?: string): string => {
    if (isCustomDomain) {
      return `/product/${productSlug || productId}/release/${releaseSlug || releaseId}/`
    }
    if (isPublicView) {
      return `/public/product/${productId}/release/${releaseId}/`
    }
    return `/product/${productId}/release/${releaseId}/`
  }
  
  /**
   * Generate URL for workspace/Trust Center page
   */
  const getWorkspaceUrl = (workspaceKey?: string): string => {
    if (isCustomDomain) {
      return `/`
    }
    if (workspaceKey) {
      return `/public/workspace/${workspaceKey}/`
    }
    return `/public/workspace/`
  }
  
  /**
   * Generate URL for product releases page
   * @param productId - Product ID (used on main app domain)
   * @param productSlug - Optional product slug (used on custom domains)
   */
  const getProductReleasesUrl = (productId: string, productSlug?: string): string => {
    if (isCustomDomain) {
      return `/product/${productSlug || productId}/releases/`
    }
    if (isPublicView) {
      return `/public/product/${productId}/releases/`
    }
    return `/product/${productId}/releases/`
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
    getReleaseUrl,
    getWorkspaceUrl,
    getProductReleasesUrl
  }
}

/**
 * Detect if current page is on a custom domain by checking the hostname
 * and comparing it with known patterns.
 * 
 * @returns boolean indicating if on a custom domain
 */
export function detectCustomDomain(): boolean {
  if (typeof window === 'undefined') {
    return false
  }
  
  const hostname = window.location.hostname
  
  // Known non-custom-domain hosts
  const knownHosts = [
    'sbomify.com',
    'app.sbomify.com',
    'localhost',
    '127.0.0.1',
    'testserver'
  ]
  
  // Check if hostname matches or ends with known hosts
  const isKnownHost = knownHosts.some(known => 
    hostname === known || hostname.endsWith('.' + known)
  )
  
  return !isKnownHost
}
