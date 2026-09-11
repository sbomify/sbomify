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

`yocto_core-image-minimal.spdx3.json` and `yocto_core-image-minimal.spdx.json`
are SBOMs for `core-image-minimal` on `qemux86-64`, built from the default
distribution (`poky`) by the Yocto Project's own autobuilder. Background:
<https://sbomify.com/2026/05/19/yocto-spdx-3-0-overview/>.

### SPDX 3.0

`yocto_core-image-minimal.spdx3.json` is the published artefact, byte for byte,
from Yocto 6.0.3 (Wrynose LTS), which emits SPDX 3.0.1 via `create-spdx-3.0`:

```bash
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-6.0.3/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.json
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-6.0.3/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.json.sha256sum
sha256sum -c core-image-minimal-qemux86-64.rootfs.spdx.json.sha256sum
mv core-image-minimal-qemux86-64.rootfs.spdx.json \
   sboms/tests/test_data/yocto_core-image-minimal.spdx3.json
```

A single JSON-LD document: 3049 graph elements, 259 `software_Package`s, plus
`build_Build` provenance and `security_Vulnerability` / VEX assessments.

### SPDX 2.3

Yocto has no SPDX 2.3 emitter — `create-spdx-2.2` is the only 2.x writer, it
hardcodes `SPDX-2.2` in `meta/lib/oe/spdx.py`, and it was dropped entirely in
Yocto 6.0. Its output is also not a single SBOM: it is a tarball of ~one
document per recipe and per package, plus a thin image document that reaches
them through `externalDocumentRefs`. Uploaded on its own that image document
yields exactly one component.

So this sample is built from the last LTS that still ships a 2.x SBOM, Yocto
5.0.19 (Scarthgap), flattened into one document and re-declared as SPDX 2.3
(a backwards-compatible superset of 2.2, so no field migration is required):

```bash
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-5.0.19/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.tar.zst
curl -O https://downloads.yoctoproject.org/releases/yocto/yocto-5.0.19/machines/qemu/qemux86-64/core-image-minimal-qemux86-64.rootfs.spdx.tar.zst.sha256sum
sha256sum -c core-image-minimal-qemux86-64.rootfs.spdx.tar.zst.sha256sum
mkdir spdx22 && tar --zstd -xf core-image-minimal-qemux86-64.rootfs.spdx.tar.zst -C spdx22

./bin/flatten_yocto_spdx.py \
    spdx22 \
    spdx22/core-image-minimal-qemux86-64.rootfs-20260702144922.spdx.json \
    sboms/tests/test_data/yocto_core-image-minimal.spdx.json
```

233 packages, 161 files, 11171 relationships, 3 extracted licenses. Package,
file, licence and relationship data is verbatim from the Yocto build; the only
edits are the ones flattening forces:

- Cross-document `DocumentRef-x:SPDXRef-y` references become document-local
  `SPDXRef-`s, prefixed with the source document name where ids would collide.
- Cross-document `DocumentRef-x:LicenseRef-y` expressions are rewritten the same
  way, and every `hasExtractedLicensingInfos` entry is merged into the document.
- The 304 document-level `DESCRIBES`/`AMENDS`/`OTHER` relationships are dropped
  — with one merged document they would be self-references — and replaced by a
  single `DESCRIBES` pointing at the image package.

Note that Yocto emits CPE external references rather than purls, so these
packages exercise the purl-less path. `GENERATED_FROM NOASSERTION` relationships
carrying a debug-source path in a comment are kept; they are most of the 11171
and most of the file size.
