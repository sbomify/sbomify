# 8. Workspace Roles as a Linear Capability Ladder

Date: 2026-08-12

## Status

Accepted

## Context

Workspace authorization grew as inline role checks. By mid-2026 roughly 120
sites spelled out `role in ("owner", "admin")` or `role == "owner"` by hand,
and "what can an admin do?" was an emergent property of those call sites rather
than something anyone could read. `sbomify/apps/core/authz.py` consolidated the
decision into `can(actor, action, resource)` backed by capability tiers, but the
role set itself remained wrong in three ways:

1. **There was no role for the ordinary user.** Someone who uploads SBOMs,
   maintains components and cuts releases had to be made an `admin`, which also
   handed them branding, integrations, controls catalogs, CRA sign-off,
   trust-center approvals and member removal.

2. **`guest` was three things at once** — an external trust-center visitor, an
   internal reader, and an artifact publisher. `READ_MEMBER` held
   `(guest, owner, admin)` and *every* read action resolved to it
   (`workspace:read`, `component:read_internal`, `product:read`, `release:read`,
   `document:read`, `sbom:read`); only `component:access` took the
   attribute-based path, so those reads were role checks with no visibility gate
   at all. `PUBLISH` held `guest` outright.

   The dangerous part was not that the model said this, but that **nothing
   agreed with it**. `GuestAccessBlockedMixin` kept guests out of the internal
   web pages; inside the API, 26 inline `_is_guest_member` checks in
   `core/apis.py` and a hardcoded refusal in `teams/apis.py` turned guests away
   on *some* endpoints. So a guest's actual access depended on whether the
   endpoint they hit happened to carry an ad-hoc guard, none of which the
   capability model knew about. The endpoints that lacked one fell through to
   the permissive tier — which is exactly where review later found three read
   paths reaching internal data, one of them unauthenticated.

   The lesson is not "the UI and the API disagreed". It is that a permissive
   tier patched over by scattered inline guards has no reviewable answer to
   "what can a guest do?", and the gaps are invisible until something enumerates
   them.

3. **`admin` was a half-owner** defined by an arbitrary list of things it could
   not reach, including deleting a product it had just created.

Underneath all three sat a fourth problem: `role="member"` existed in the
database for years without existing in the code. Django's `choices` is not
enforced by PostgreSQL and `Member.save()` deliberately skips `full_clean()`, so
the value was accepted by every persistence path while matching no role check.
It was worked around by defensive comments in three files rather than fixed.

## Decision

**Roles form a linear capability ladder: `guest ⊂ member ⊂ admin ⊂ owner`.**

| Role | What it is |
| --- | --- |
| `owner` | Full control. |
| `admin` | Near-owner. Runs the workspace day to day, including settings, billing and members. |
| `member` | Day-to-day contributor: create/edit products, components and releases; upload artifacts; cut releases; triage vulnerabilities. |
| `guest` | External. Holds **no** capability tier at all. |
| `bot` | Synthetic OIDC publishing identity. Outside the ladder; never human-assignable. |

Three rules follow from this, and they are the point of the ADR:

**1. The ladder stays linear.** No role may hold a capability a more-privileged
role lacks. `test_role_ladder_is_upward_closed` asserts this across every action,
so a carve-out that breaks inheritance fails in CI rather than in production.

**2. Granularity is added as a tier, never as a per-user permission bundle or a
per-resource ACL.** Every battle-tested model we looked at (GitLab, Sentry,
GitHub) is a ladder. The counter-example is instructive: OWASP Dependency-Track,
the closest domain peer, grants named permissions to teams plus per-project
portfolio ACLs, and its issue tracker carries long-running threads about uploads
failing on a missing permission and ACLs behaving unpredictably for users in
several teams. Snyk landed in the same place and had to add custom roles on top.
Four roles and one table is the simple end, and we stay there.

**3. External users are a separate concept, not the bottom rung.** A guest
`Member` row is an ACL anchor for the access-request/NDA machinery, not a
capability grant. Guests reach restricted content solely through the
attribute-based `component:access` path (visibility + approved request + signed
NDA), never through a role check. This mirrors GitHub's "outside collaborator".

### Carve-outs

Two capabilities sit above `MANAGE` despite looking like routine work, because
they are outward-facing rather than reversible-in-private:

- `product:set_visibility` / `component:set_visibility` — publishing to the
  public trust center.
- `component:manage_publishers` — an OIDC trusted-publisher binding is a
  standing, non-expiring publish grant to an external repository, unlike a
  personal access token, which is scoped, expiring and tied to one person.

One capability is reserved to the owner: `workspace:delete`. The other
owner-exclusive rule — *an admin may not remove an owner* — is **relational**: it
depends on the target member's role, not just the actor's, so it cannot be
expressed as a tier and lives in `teams.permissions.check_member_removal()`.

### Integrity

`Member.role` carries a `member_role_is_supported` CheckConstraint. This is what
prevents another `"member"`: it covers `bulk_create()`, raw SQL, fixtures and
admin actions alike, none of which run `full_clean()`.

## Consequences

**Admins gained** deletion of domain resources, workspace settings, custom
domain, trust-center configuration, billing and invitations. Notably, admins may
invite at owner level. That makes the owner/admin boundary a speed bump rather
than a security boundary — an admin can mint an owner they control — and we
accept it deliberately: the boundary exists to prevent accidents, not to defend
against a malicious admin. The mitigation is visibility, not prohibition:
existing owners are notified when a non-owner creates an owner-level invitation.

**Guests lost** every internal read endpoint and artifact upload. This is a
breaking API change for any guest holding a personal access token, and guests can
mint tokens (`core:settings` is login-gated, not role-gated), so deployments
should audit before upgrading.

**Templates must not branch on the session role.** `session["current_team"]["role"]`
is a cache with a 300s TTL; gates read the capability flags from
`core.context_processors.team_context`, which resolve from the live `Member` row.

**Billing was deliberately not split out.** GitHub and Sentry both model billing
as an orthogonal role rather than a rung. We gave it to admins instead — one
fewer role. If "finance shouldn't be an admin" ever becomes a real requirement,
the answer is a separate orthogonal role or flag, **not** a new rung in the
ladder.
