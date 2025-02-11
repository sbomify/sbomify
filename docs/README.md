# Security Artifact Hub Documentation

## Overview

This documentation describes the architecture and implementation of the Security Artifact Hub, a platform for managing and discovering security-related artifacts such as SBOMs, VEX files, and compliance documentation.

## Quick Links

- [Architecture Overview](architecture/README.md)
- [API Documentation](api/README.md)
- [API Reference](api/v2-specification.md)
- [Common Use Cases](api/use-cases.md)

## Contents

### [Architecture](architecture/README.md)

- [System Overview](architecture/README.md#system-overview)
- [Core Concepts](architecture/README.md#core-concepts)
- [Data Models](architecture/data-model.md)
- [Release Management](architecture/releases.md)
- [API Design](architecture/api-design.md)

### [API Documentation](api/README.md)

- [API Reference](api/v2-specification.md)
- [Common Use Cases](api/use-cases.md)
- [Migration Guide](api/migration.md)
- [Transparency Exchange](api/transparency-exchange.md)
- [Release-Based Architecture](architecture/releases.md)

### Development

- [Getting Started](api/use-cases.md#getting-started)
- [Best Practices](api/use-cases.md#best-practices)
- [Examples](api/use-cases.md#examples)

## Migration Guide

### From SBOM-only to Security Artifact Hub

The platform is evolving from an SBOM-focused system to a comprehensive security artifact management platform. Here's what you need to know:

1. **API Changes**
   - V1 API (`/api/v1/`) remains fully functional for SBOM operations
   - V2 API (`/api/v2/`) introduces unified artifact handling
   - [Detailed API comparison](api/migration.md)

2. **Data Migration**
   - Existing SBOMs are automatically migrated to the new artifact system
   - No action required for existing integrations
   - New features available through V2 API

3. **New Capabilities**
   - Multi-format artifact support (SBOM, VEX, Certifications)
   - Enhanced relationship management
   - Advanced search and discovery
   - [Feature overview](architecture/releases.md#core-concepts)

4. **Timeline**
   - V2 API: Available now
   - V1 API: Maintained for backward compatibility
   - Future deprecation notices will be announced 12 months in advance

## Support

- [GitHub Issues](https://github.com/sbomify/issues)
- [Documentation Updates](api/migration.md#support)
