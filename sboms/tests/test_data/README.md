# SBOM Generation

This is our test data set for SBOMs.

## Trivy

```bash
trivy fs poetry.lock \
    --format spdx-json \
    > sboms/tests/test_data/sbomify_trivy.spdx.json
```

```bash
trivy fs poetry.lock \
    --format cyclonedx \
    > sboms/tests/test_data/sbomify_trivy.cdx.json
```

## Syft

```bash
syft scan poetry.lock \
    -o cyclonedx-json \
    > sboms/tests/test_data/sbomify_syft.cdx.json
```

```bash
syft scan poetry.lock \
    -o spdx-json \
    > sboms/tests/test_data/sbomify_syft.spdx.json
```

## Parlay

We also generate an "enriched" version of all the above SBOMs
using `parlay` for test purposes.

All of these can be generate with:

```bash
parlay ecosystems enrich sbomify_[...].json > sbomify_[...].json
```
