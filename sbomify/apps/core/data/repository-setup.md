# Set up sbomify for a repository

These are the standing instructions. The prompt you were given carries the
parts that change per run: the API token, and whether to create things private
or public. Everything else is here.

## What sbomify is

sbomify tracks what your software is made of. Each build uploads an SBOM, a
machine-readable list of every dependency and version that shipped. sbomify
scans those for known vulnerabilities and keeps the record that customers and
auditors ask for. A product is a thing you ship, a component is one buildable
part of it, and one lockfile becomes one component. Each configured run uploads a fresh
SBOM against its component. Monitor failed or missing runs separately.

## Before you start

    API      Use the API URL in the prompt. OpenAPI is at the same origin: /api/v1/docs
    Auth     Authorization: Bearer <the token in your prompt>
    Client   Use curl for API calls.

Use the workspace-scoped setup token from the prompt. Visibility and publisher bindings require an owner or admin. Review the proposed records and bindings before writing. Revoke the setup token after completion; automatic revocation is not guaranteed. Use it for these API calls only. Never write it to a file, a CI secret
or the workflow. The workflow authenticates over OIDC, not this token.

## 1. Survey, before creating anything

1. Find every lockfile. Skip `node_modules`, `vendor`, `.venv`, `dist` and
   `build`. List what you found. Flag any that carry version ranges rather
   than exact versions, since those produce vague SBOMs.
2. `GET /workspaces/` to find the workspace bound to the token. Use its `key`
   in `GET /billing/usage/?team_key=<key>`. Read `/billing/plans/`, `/products`
   and `/components`. Work out how many product and component slots are left. If
   there are fewer free slots than lockfiles, stop and show the shortfall
   with options.
3. Leave any existing product or component alone. Never rename or delete one
   to free a slot without asking first.

## 2. Create

1. Propose the product, component mappings, visibility and OIDC bindings for review first. Reuse matching existing records. Create only missing records with `POST /products`, one product named after this repo.
   `POST /components`, one per lockfile, `component_type` `"bom"`. Name each
   after its repo-relative path, never its basename: several directories may
   each hold a `requirements.txt` and the names have to stay unique.
   `PATCH /products/{id}` with `component_ids` to attach them.
2. `POST /auth/oidc/github/bindings`, one binding per component, bound to
   this repo as `owner/name`. Without these the workflow has nothing to
   exchange its OIDC token against and every run fails auth.
3. Set visibility explicitly to the choice in the prompt. Products use
   `is_public` (a boolean); components use `visibility` (`"public"` or `"private"`). Do not rely on the default. If the plan refuses that
   visibility, stop and say so before anything is uploaded.

## 3. Workflow

1. Write `.github/workflows/sboms.yml` running `sbomify/sbomify-action` once
   per lockfile, each step carrying its own `COMPONENT_ID` and `LOCK_FILE`.
   Also:
   - reference the action by the commit SHA of its latest release tag, with the tag
     in a trailing comment
   - `permissions: id-token: write` and `contents: read`
   - trigger on push to the default branch filtered to the covered lockfile
     paths, plus `workflow_dispatch`. Keep it to one job, runner minutes bill
   - match the naming and comment style of the other files in that directory
   - leave a TODO naming any lockfile you could not cover, and what would
     unblock it

   Reference: <https://github.com/sbomify/sbomify-action>

   For a self-hosted instance, use the API origin in the prompt as
   `API_BASE_URL` in the workflow. Confirm that the CI runner can reach it.
   A localhost address only works on that machine, so ask for the reachable
   instance URL before writing a hosted workflow.

## 4. Finish

1. Show the workflow before committing. Do not commit until told to, and
   never merge. Branch first if on the default branch. Change nothing else.

Report the product ID, every component ID against its lockfile, any lockfile
left uncovered and why, and anything that weakens this setup rather than
assuming it is fine: action references without a fixed commit, plan limits, a setting you
could not apply.

If something blocks you, do not narrow the job. Say so and let the person
choose.
