# sbomify Newsletter Template

An [MJML](https://mjml.io/) template for the sbomify newsletter. MJML compiles to
responsive, email-client-safe HTML (including Outlook), so we only maintain the
high-level markup here.

The newsletter is sent through **Mailjet**: upload `sbomify-newsletter.mjml`
itself to Mailjet's template editor — its importer only accepts `.mjml` files,
not compiled HTML. The footer already uses Mailjet's reserved link tags
(`[[UNSUB_LINK_EN]]`, `[[PERMALINK]]`), which Mailjet resolves at send time.

**Keep the template Passport-safe.** Mailjet's editor (Passport) is not the
reference MJML compiler — it only imports the subset of MJML its drag-and-drop
model can represent. The template therefore inlines every attribute and avoids
head-level styling and layout tricks. When editing, do not add:

- `mj-attributes` / `mj-class` / `mj-style` (inline attributes on each element instead)
- `mj-group`, `mj-spacer`, or multi-column layout tricks
- HTML comments before the `<mjml>` tag

Standard MJML that compiles fine with `mjml` CLI can still be rejected by
Mailjet's importer if it uses those constructs.

The design matches the transactional email branding in
`sbomify/apps/core/templates/core/emails/base.html.j2`: dark navy header with the
white logo and "The Security Artifact Hub" tagline, brand blue (`#4059d0`)
buttons and links, and a solid brand-pink accent divider under the header and
above the CTA band (a stepped brand-gradient bar isn't representable in
Passport-safe MJML — see the constraints above).

## Compiling

No install needed — run from the repo root:

```bash
bunx mjml@5.4.0 newsletter/sbomify-newsletter.mjml -o newsletter/sbomify-newsletter.html
```

Preview while editing:

```bash
bunx mjml@5.4.0 --watch newsletter/sbomify-newsletter.mjml -o /tmp/newsletter.html
```

The version is pinned to match the CI workflow so local output is identical to
the build artifact.

You can also paste the template into the [MJML live editor](https://mjml.io/try-it-live)
for a quick visual preview.

Alternatively, run the **Build Newsletter** workflow from the GitHub Actions tab
(`.github/workflows/newsletter.yml`, manual trigger). It uploads a `newsletter`
build artifact containing both the `.mjml` source (for Mailjet import) and the
compiled `.html` (for previewing or non-Mailjet use).

## Writing an issue

1. Copy `sbomify-newsletter.mjml` (or edit in place and don't commit the issue).
2. Replace every `##PLACEHOLDER##` — issue title, preview text, intro, featured
   story, product updates, and reading links. Drop sections that don't apply for
   a given issue (e.g. remove an update block or the "Worth reading" box).
   Don't write placeholders in `[[double square brackets]]` — Mailjet reserves
   that syntax for its own link tags.
3. Keep the footer's `[[UNSUB_LINK_EN]]` and `[[PERMALINK]]` tags as-is, and
   replace `##SENDER_POSTAL_ADDRESS##` with the real postal address — the
   unsubscribe link and address are legally required (CAN-SPAM/GDPR). Mailjet
   refuses to send campaigns without an unsubscribe tag.
4. Upload the `.mjml` file to Mailjet's template editor and send from there.

## Notes

- The header logo is loaded from `https://app.sbomify.com/static/img/sbomify-white.svg`.
  Some clients (notably Gmail) don't render SVG images — if that matters for your
  audience, upload a white-on-transparent PNG to the ESP's CDN and swap the URL.
- Images should be hosted at 2× their display width for retina screens (the
  feature image slot displays at 520px inside a 600px layout, so upload ~1040px).
- Keep `mj-preview` text meaningful — it's the snippet shown next to the subject
  line in most inboxes.
