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

SBOMs for `core-image-minimal` on `qemux86-64`, built from the default
distribution (`poky`) by the Yocto Project's own autobuilder. Both are the
published artefacts byte for byte — only the filenames differ, to match the
naming used in this directory. Background:
<https://sbomify.com/2026/05/19/yocto-spdx-3-0-overview/>.

Note that Yocto emits CPE external references rather than purls, so these
samples exercise the purl-less path.

### SPDX 3.0

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

### SPDX 2.2

`yocto_core-image-minimal.spdx.tar.zst`, from Yocto 5.0.19 (Scarthgap LTS) —
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
and links them with `externalDocumentRefs` — that multi-document shape *is* the
output, and flattening it here would mean shipping something Yocto never
produced.

```
tar --zstd -xf yocto_core-image-minimal.spdx.tar.zst -C <dir>
```

176 SPDX documents plus an index:

- `index.json` — maps every `documentNamespace` to its filename and sha1.
- `core-image-minimal-qemux86-64.rootfs-20260702144922.spdx.json` — the image
  document. One package, no files, and 72 `externalDocumentRefs`; its
  `CONTAINS` relationships are what point at the packages in the rootfs.
- `<package>.spdx.json` — the binary packages, with licences, checksums and
  packaged files.
- `recipe-<name>.spdx.json` — the source recipes the packages are
  `GENERATED_FROM`.
- `runtime-<name>.spdx.json` — runtime dependency relationships.

Across all of them: 233 packages, 161 files, 11474 relationships, and 6
documents carrying `hasExtractedLicensingInfos`. Note that `LicenseRef-`s are
scoped per document, so licence expressions can read
`GPL-2.0-only AND DocumentRef-recipe-busybox:LicenseRef-bzip2-1.0.4`.
