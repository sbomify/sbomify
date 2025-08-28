import 'vite/modulepreload-polyfill'

// Note: Most components converted to Django templates
// Still keeping some Vue components that require complex interactivity:
// - LicensesEditor (complex form with dynamic fields)
// - CiCdInfo (complex metadata editing)
// - SbomUpload (file upload with progress)
// - SbomMetadataCard (complex metadata display)
// - SbomActionsCard (complex actions with confirmations)

// Vue components are available but not automatically mounted
// Import and mount them as needed in specific pages
// mountVueComponent('vc-ci-cd-info', CiCdInfo)
// mountVueComponent('vc-sbom-upload', SbomUpload)
// Dashboard stats now use Django templates with server-side rendering
// mountVueComponent('vc-sbom-metadata-card', SbomMetadataCard)
// mountVueComponent('vc-sbom-actions-card', SbomActionsCard)
// Note: SbomsTable and NTIA Compliance Badge converted to Django templates
