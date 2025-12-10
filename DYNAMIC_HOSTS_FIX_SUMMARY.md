# Dynamic Hosts Bug Fix - Summary

## Problem

Custom domains like `trust.sbomify.com` were being rejected by Django with `DisallowedHost` errors, even though:

- DNS was configured correctly
- SSL certificates were issued by Caddy
- The domain existed in the database

## Root Cause

**Django 4.0+ Breaking Change**: Django now enforces that `ALLOWED_HOSTS` must be a plain `list` or `tuple`. The custom `DynamicAllowedHosts` class with `__contains__` method was being converted to a plain list during settings validation, breaking the dynamic lookup logic.

## Solution Implemented

Replaced the incompatible `DynamicAllowedHosts` class with **middleware-based validation**:

### Changes Made

1. **New Middleware** (`sbomify/apps/core/middleware.py`)
   - Added `DynamicHostValidationMiddleware` class
   - Three-tier validation:
     - **Tier 1**: Static hosts (in-memory set lookup - instant)
     - **Tier 2**: APP_BASE_URL (cached at module load)
     - **Tier 3**: Custom domains (Redis cache + DB fallback)
   - Valid domains cached for 1 hour
   - Invalid domains cached for 5 minutes

2. **Settings Updates** (`sbomify/settings.py`)
   - Removed `DynamicAllowedHosts` class entirely
   - Changed `ALLOWED_HOSTS` to `["*"]`
   - Added middleware to `MIDDLEWARE` list (after SecurityMiddleware)

3. **Test Settings** (`sbomify/test_settings.py`)
   - Updated to use same approach
   - Removed `DynamicAllowedHosts` import

4. **Cache Key Updates** (`sbomify/apps/teams/utils.py`)
   - Updated `invalidate_custom_domain_cache()` to use new cache key: `allowed_host:{domain}`
   - Updated docstring references

5. **Comprehensive Tests** (`sbomify/apps/teams/tests/test_domain_middleware.py`)
   - Rewrote tests to test middleware instead of `__contains__`
   - Added tests for:
     - Static host validation
     - Invalid domain rejection
     - Custom domain acceptance
     - Port handling
     - Caching behavior

## Performance Characteristics

- **Static hosts**: O(1) in-memory set lookup (no cache/DB hit)
- **Cached domains**: Single Redis GET (microseconds)
- **Cache miss**: Single DB query, then cached

**Result**: The vast majority of requests hit Redis cache with no DB access.

## Testing Results

All tests passing:

- ✅ `test_domain_middleware.py` (5 tests)
- ✅ `test_domain_management.py` (12 tests)
- ✅ `test_internal_apis.py` (19 domain-related tests)

## Migration Path

1. ✅ Created new middleware class
2. ✅ Updated settings files
3. ✅ Updated cache invalidation logic
4. ✅ Rewrote tests
5. ⏳ Deploy to production
6. ⏳ Verify `trust.sbomify.com` works

## Expected Behavior After Deployment

When you deploy this fix:

1. **Existing domains** (like `trust.sbomify.com`) will immediately work
2. **New domains** added via API will work instantly
3. **Cache invalidation** happens automatically when domains are added/removed
4. **Performance** is excellent with Redis caching

## Files Changed

- `sbomify/apps/core/middleware.py` - Added new middleware
- `sbomify/settings.py` - Removed old class, updated ALLOWED_HOSTS and MIDDLEWARE
- `sbomify/test_settings.py` - Updated for compatibility
- `sbomify/apps/teams/utils.py` - Updated cache key and comments
- `sbomify/apps/teams/tests/test_domain_middleware.py` - Rewrote tests

## Verification Steps

After deploying:

1. Test that `trust.sbomify.com` works:

   ```bash
   curl -v https://trust.sbomify.com/.well-known/com.sbomify.domain-check
   ```

   Should return 200 with JSON response

2. Check logs for middleware validation:
   - Valid domains should pass silently
   - Invalid domains should show: "Invalid host header rejected: {domain}"

3. Verify caching in Redis:

   ```bash
   redis-cli GET "allowed_host:trust.sbomify.com"
   ```

   Should return "1" (true) if cached
