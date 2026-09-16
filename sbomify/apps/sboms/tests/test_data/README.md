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

## Yocto

SBOMs for `qemux86-64` images, built from the default distribution (`poky`) by
the Yocto Project's own autobuilder. The downloaded content is preserved byte for byte in
all three. Only the filenames differ, to match the naming used in this
directory, and the largest is gzipped for repository storage, so that file is a
gzip wrapper around the published JSON rather than the JSON itself. Background:
<https://sbomify.com/2026/05/19/yocto-spdx-3-0-overview/>.

Two of them are the same image at two spec versions; the third is a much larger
image, for exercising the paths where document size is the variable rather than
the shape.

| Sample | Elements | Packages | purl | cpe | neither |
| --- | --- | --- | --- | --- | --- |
| 6.0.3 `core-image-sato-sdk` (SPDX 3.0) | 68511 | 3813 | 2206 | 2053 | 1607 |
| 6.0.3 `core-image-minimal` (SPDX 3.0) | 3049 | 259 | 161 | 151 | 98 |
| 5.0.19 `core-image-minimal` (SPDX 2.2) | n/a | 233 | 0 | 102 | 131 |

Yocto always emits CPE external references, from `CVE_PRODUCT`/`CVE_VERSION`.
Whether it also emits purls changed between releases, so the samples do not all
exercise the same path: the 2.2 sample is the purl-less one, while on both 3.0
samples most packages carry both, and a test meaning to exercise CPE identity
there would pass on the purl instead. Note that the 3.0 purls live in the
`software_packageUrl` property, not only in `externalIdentifier`. 43 of the
sato-sdk packages have the property and no matching external identifier, so
counting one source alone undercounts.

The packages carrying neither are source archives (`acl-2.3.2.tar.gz`, git
checkouts versioned by commit), not shipped software: 97 of the 98 on the
minimal 3.0 sample and 1606 of the 1607 on sato-sdk have
`software_primaryPurpose: source`. On what the images install, coverage is
151 of 153 and 1600 of 1600 respectively.

The 2.2 sample carries no VEX at all. SPDX 2.2 has no security profile, so
`CVE_STATUS` has nowhere to live; its only annotations are `isNative` markers.
VEX begins with the 3.0 output.

### SPDX 3.0: core-image-minimal

`yocto_core-image-minimal.spdx3.json`, from Yocto 6.0.3 (Wrynose LTS), which
emits SPDX 3.0.1 via `create-spdx-3.0`:

```bash
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-6.0.3/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.json
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-6.0.3/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.json.sha256sum
sha256sum -c core-image-minimal-qemux86-64.rootfs.spdx.json.sha256sum
mv core-image-minimal-qemux86-64.rootfs.spdx.json \
   sboms/tests/test_data/yocto_core-image-minimal.spdx3.json
```

`sha256: 42fa3058205fe486bf0804fb1f5aab72bd73a2bd724ca0e267c242d9f9c1da17`

A single JSON-LD document: 3049 graph elements, 259 `software_Package`s, plus
`build_Build` provenance and `security_Vulnerability` / VEX assessments.

### SPDX 3.0: core-image-sato-sdk (large)

`yocto_core-image-sato-sdk.spdx3.json.gz`, from the same Yocto 6.0.3 autobuilder
run as the minimal sample above. Both carry the `20260819091134` build stamp.
`core-image-sato-sdk` is the largest image poky publishes an SBOM for: the
Sato GTK+/X11 desktop plus a full on-target SDK, which is what makes the
document big rather than any post-processing on our side. Counting from the
document itself, its 1600 installed packages include gcc, binutils, make, gdb,
llvm, perf, systemtap, valgrind, strace, lttng, python3, the matchbox desktop,
`kernel-devsrc` and 369 `-dev` packages. Upstream that comes from the recipe
adding `dev-pkgs tools-sdk tools-debug tools-profile tools-testapps` to
`IMAGE_FEATURES` on top of `core-image-sato` (checked on poky `walnascar`; the
6.0 branch is not on the public mirror, so treat the feature list as
indicative and the package counts above as measured).

```bash
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-6.0.3/machines/qemu/qemux86-64/core-image-sato-sdk-qemux86-64.rootfs.spdx.json
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-6.0.3/machines/qemu/qemux86-64/core-image-sato-sdk-qemux86-64.rootfs.spdx.json.sha256sum
sha256sum -c core-image-sato-sdk-qemux86-64.rootfs.spdx.json.sha256sum
gzip -9 -n -c core-image-sato-sdk-qemux86-64.rootfs.spdx.json \
   > sboms/tests/test_data/yocto_core-image-sato-sdk.spdx3.json.gz
```

`sha256` of the uncompressed document:
`ad7c716ee239032369ebc07d4eb5ef9eb1d87394dd6ff43a99298cf1a50fd481`

The document is 50 MiB uncompressed and 4.2 MiB committed. It is stored gzipped
rather than zstd, unlike the 2.2 tarball whose `.zst` is Yocto's own framing,
so that it opens in-process with no dependency beyond the standard library:

```python
import gzip
import json

with gzip.open("yocto_core-image-sato-sdk.spdx3.json.gz") as fh:
    document = json.load(fh)
```

That costs about 0.4s, so a test can afford to load it, just not per test case.

`gzip -9 -n` is what produced the committed bytes; the `-n` keeps the filename
and mtime out of the header so regenerating it is reproducible.

One JSON-LD document, 68511 graph elements:

| Element | Count |
| --- | --- |
| `software_File` | 50828 |
| `Relationship` + `LifecycleScopedRelationship` | 12171 |
| `software_Package` | 3813 |
| `build_Build` | 566 |
| `CreationInfo` | 383 |
| `security_Vulnerability` | 291 |
| `security_VexFixedVulnAssessmentRelationship` | 205 |
| `security_VexNotAffectedVulnAssessmentRelationship` | 86 |
| `simplelicensing_LicenseExpression` | 149 |

The 3813 packages split by `software_primaryPurpose` into 1649 `source`, 1600
`install`, 563 `specification` and 1 `archive`. Of the 86 not-affected VEX
relationships, 37 carry a `security_justificationType` and 49 do not.

Every element validates against the vendored `spdx_3.0.1-schema.json`, but note
that `spdx3_validation.MAX_VALIDATED_ELEMENTS` caps the runtime check at 500.
This document is 137× that cap, which is the point of having it. Checking all
68511 took roughly 50 minutes of CPU here (5m22s wall across ten cores), so
validate it out-of-band, not in a test that runs per-commit.

### SPDX 2.2

`yocto_core-image-minimal.spdx.tar.zst`, from Yocto 5.0.19 (Scarthgap LTS),
the last LTS that still ships a 2.x SBOM. It is **2.2, not 2.3**: Yocto has no
SPDX 2.3 emitter. `create-spdx-2.2` is the only 2.x writer, it hardcodes
`SPDX-2.2` in `meta/lib/oe/spdx.py`, and it was dropped entirely in Yocto 6.0.

```bash
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-5.0.19/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.tar.zst
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-5.0.19/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.tar.zst.sha256sum
sha256sum -c core-image-minimal-qemux86-64.rootfs.spdx.tar.zst.sha256sum
mv core-image-minimal-qemux86-64.rootfs.spdx.tar.zst \
   sboms/tests/test_data/yocto_core-image-minimal.spdx.tar.zst
```

`sha256: 881fb2a6c4ffc303750e480ac3eafe0dd1c4877ce5c2cb8836ba43c190e38066`

This is kept as the tarball on purpose. SPDX 2.2 has no way to express a whole
image in one document, so Yocto emits ~one document per recipe and per package
and links them with `externalDocumentRefs`. That multi-document shape *is* the
output, and flattening it here would mean shipping something Yocto never
produced.

```bash
tar --zstd -xf yocto_core-image-minimal.spdx.tar.zst -C <dir>
```

176 SPDX documents plus an index:

- `index.json`: maps every `documentNamespace` to its filename and sha1.
- `core-image-minimal-qemux86-64.rootfs-20260702144922.spdx.json`: the image
  document. One package, no files, and 72 `externalDocumentRefs`; its
  `CONTAINS` relationships are what point at the packages in the rootfs.
- `<package>.spdx.json`: the binary packages, with licences, checksums and
  packaged files.
- `recipe-<name>.spdx.json`: the source recipes the packages are
  `GENERATED_FROM`.
- `runtime-<name>.spdx.json`: runtime dependency relationships.

Across all of them: 233 packages, 161 files, 11474 relationships, and 6
documents carrying `hasExtractedLicensingInfos`. Note that `LicenseRef-`s are
scoped per document, so licence expressions can read
`GPL-2.0-only AND DocumentRef-recipe-busybox:LicenseRef-bzip2-1.0.4`.
