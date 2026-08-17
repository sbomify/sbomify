# sbomify Keycloak theme

The login, registration and account-recovery pages Keycloak serves. Keycloak
runs on its own origin, so it cannot use the app's stylesheet or component
library. This theme is a standalone Tailwind build that mirrors the app's design
tokens instead.

## The two rules

**1. Filenames are a contract.** Keycloak resolves each page by a fixed
filename. A file named anything else is never loaded, and Keycloak silently
falls back to its own unstyled page. This is not a hypothetical: `forgot-password.ftl`
and `update-password.ftl` sat in this directory for months and never rendered
once, because the real names are `login-reset-password.ftl` and
`login-update-password.ftl`.

Before adding a page, confirm the name against the base theme:

```bash
docker cp <keycloak-container>:/opt/keycloak/lib/lib/main/org.keycloak.keycloak-themes-*.jar .
unzip -l org.keycloak.keycloak-themes-*.jar | grep -oE 'theme/base/login/[a-z0-9-]+\.ftl'
```

Message bundles follow the same rule: Keycloak loads
`login/messages/messages_<locale>.properties` by convention. A bundle named
anything else (`Messages.properties`, say) is ignored, and every override in it
is dead.

**2. Tokens are mirrored, never invented.** The `:root` block in
`login/resources/css/sbomify.src.css` is a copy of the app's dark-theme tokens
from `sbomify/assets/css/tailwind.src.css`. When a token changes there, change
it here. No rule in this file may use a raw hex value.

These pages are dark only. The app defaults a first-time visitor to dark and
switches on a stored preference that Keycloak cannot read across the origin
boundary, so dark is the honest match for what the user sees after signing in.

## Structure

```text
themes/sbomify/
├── theme.properties              # Shared: parent, locales, stylesheet
├── login/
│   ├── theme.properties          # Login-type theme config
│   ├── template.ftl              # Head, fonts, page shell
│   ├── components.ftl            # Shared macros (see below)
│   ├── messages/
│   │   └── messages_en.properties
│   ├── login.ftl                 # Sign in
│   ├── login-reset-password.ftl  # Forgot password
│   ├── login-update-password.ftl # Set a new password
│   ├── register.ftl              # Create account
│   ├── login-verify-email.ftl    # Check your inbox
│   ├── login-username.ftl        # Username step (identity-first flow)
│   ├── login-update-profile.ftl, update-email.ftl
│   ├── login-idp-link-confirm.ftl, login-idp-link-email.ftl
│   ├── info.ftl, error.ftl, terms.ftl
│   ├── logout-confirm.ftl, login-page-expired.ftl
│   └── resources/css/
│       ├── sbomify.src.css       # Source (edit this)
│       └── sbomify.css           # Compiled (committed, do not edit)
└── email/                        # Email templates
```

## Macros in `components.ftl`

| Macro | Use for |
| --- | --- |
| `brandLogo` | Inline animated wordmark. Inlined rather than `<img>` because Chrome freezes CSS animation inside an external SVG document. |
| `alertBanner` | The message banner every form page opens with. Renders nothing when there is no message. |
| `formScripts` | Client-side validation for a form. Takes `formId`, `submittingText`, and optionally `passwordMatch` with `passwordId`/`passwordConfirmId`. |
| `emailVerificationContent` | Body of the verify-email page. |

`formScripts` is called at the top of a form, before the fields exist in the
DOM, so it defers everything to `DOMContentLoaded`. Do not remove that guard:
without it `getElementById` returns null and every field listener silently fails
to attach, which is how the validation in this theme was broken for its whole
life before it was noticed.

## CSS conventions

The class vocabulary is this theme's own (`form-card`, `btn-submit`,
`form-control`) rather than the app's `tw-*` names, because most of it has to
match class names Keycloak itself emits. The design language is shared, though,
and comes from the Frontend (UI) section of `AGENTS.md`:

- Containers sit still. No hover lift, no ambient animation. Entrances are
  one-shot and motion respects `prefers-reduced-motion`.
- Filled buttons use the primary recipe: a `135deg` gradient from `--btn-accent`
  to `--btn-accent-dark`, a `0.5px` self-coloured border and an inset top
  highlight. A variant sets those custom properties, it does not restate the
  rules. The same pattern drives `--alert-accent`.
- Text on a tint mixes toward the theme text colour
  (`color-mix(in oklab, var(--accent) 60%, var(--color-text))`), never a raw
  accent on its own tint.
- State styling hangs off the real control (`:checked`, `:focus-visible`,
  `[aria-invalid="true"]`, `.input-invalid`), never a decorative sibling.

Nothing may go in the Keycloak fallback block at the bottom that also matches
themed markup. A `.login-pf-page .form-control` rule there once matched every
themed field at the same specificity while sitting later in the file, which
silently disabled the error border everywhere.

## Copy

Follows the copy rules in `AGENTS.md`: sentence case, short sentences, plain words,
no em or en dashes, and a button says the action it performs ("Send reset link",
not "Submit"). Overrides live in `login/messages/messages_en.properties`.

## Building

```bash
cd keycloak
bun run build   # compile and minify
bun run dev     # watch
```

The compiled `sbomify.css` is committed, so rebuild and commit it with any CSS
change. Templates need no build step.

Tailwind has no `theme.extend` here on purpose: colour, radius, shadow and type
all come from the tokens in the stylesheet. A palette in `tailwind.config.ts`
would be a second source of truth that drifts from the app.

## Local development

The theme is bind-mounted read only:

```yaml
keycloak:
  volumes:
    - ./keycloak/themes:/opt/keycloak/themes:ro
```

Keycloak runs with `start-dev`, which disables theme caching, so template edits
show on refresh and CSS edits show after `bun run build`.

The realm is configured by `bin/keycloak-bootstrap.sh`, which sets
`loginTheme`, `emailTheme`, `registrationAllowed` and `resetPasswordAllowed`.
After changing it, re-run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up keycloak-bootstrap
```

To reach `login-update-password.ftl` without a working mailbox, set a required
action on a test user and sign in as them:

```bash
docker exec <keycloak-container> /opt/keycloak/bin/kcadm.sh update users/<id> \
  -r sbomify -s 'requiredActions=["UPDATE_PASSWORD"]'
```

## Known gaps

- **No SMTP in dev.** The bootstrap does not configure Keycloak's mail server,
  so the reset email is never delivered locally and the emailed-link path cannot
  be exercised end to end. The compose file does define a `mailpit` service.
- **`login-config.ftl` is dead.** It is a generic required-actions page, but no
  Keycloak template has that name, so it is never loaded. The nearest real name
  is `login-config-totp.ftl`, which is specifically the authenticator-setup page
  and would need different content. Adapt it or delete it.
- **Copy is only converted on the pages that were restyled** (`login`,
  `login-reset-password`, `login-update-password`). `register.ftl` and the info
  pages still carry Title Case headings.
