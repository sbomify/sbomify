"""Team-scoped contact accessors.

Single source of truth for "which entity plays role X for this team?"
Consumers — currently the CRA compliance pipeline (document generation,
export packaging, wizard step builders, auto-fill) — call these
helpers instead of filtering ``ContactEntity`` / ``ContactProfileContact``
directly against ``profile__team`` / ``entity__profile__team``. That
keeps the "find the manufacturer / security contact" rule in one place
and lets the teams app own the model layout (``ContactProfile`` →
``ContactEntity`` → ``ContactProfileContact``) without other apps
having to know it.

Anti-Corruption Layer in the spirit of
https://martinfowler.com/bliki/AntiCorruptionLayer.html: compliance
stays a consumer of teams' domain and doesn't need to grow knowledge
of teams' internal schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sbomify.apps.teams.models import ContactEntity, ContactProfileContact

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team


def get_manufacturer(team: Team) -> ContactEntity | None:
    """Return the team's configured manufacturer entity, or None.

    Walks ``ContactProfile → ContactEntity`` — the entity is scoped to
    any profile within the team, not pinned to the default profile.
    The data model only enforces "one manufacturer per profile"
    (``ContactEntity.clean``), so a team with multiple profiles can
    legitimately carry multiple manufacturer entities. The selection
    below is deterministic: prefer shared (non-component-private)
    profiles, then the default profile, then stable ordering by profile
    name and entity id — so the CRA wizard always picks the same entity
    across runs regardless of insertion order.
    """
    return (
        ContactEntity.objects.filter(
            profile__team=team,
            is_manufacturer=True,
        )
        .order_by("profile__is_component_private", "-profile__is_default", "profile__name", "id")
        .first()
    )


def get_security_contact(team: Team) -> ContactProfileContact | None:
    """Return the team's designated security contact, or None.

    Walks ``ContactProfile → ContactEntity → ContactProfileContact``
    so the contact can live under any profile within the team. Used
    by the CRA wizard to auto-fill ``csirt_contact_email`` on a new
    assessment (Article 14) and by the DoC renderer for the inline
    security-contact line on user instructions.
    """
    return (
        ContactProfileContact.objects.filter(
            entity__profile__team=team,
            is_security_contact=True,
        )
        .select_related("entity")
        .first()
    )


def list_workspace_contacts(team: Team) -> list[dict[str, Any]]:
    """Return contact dicts for every public profile in the team.

    Used by the CRA wizard's Step 4 support-contact dropdown. Excludes
    private profiles (``profile.is_component_private=True``) because
    those are scoped to individual components and shouldn't surface as
    workspace-level support contacts.

    Returned keys: ``id``, ``name``, ``email``, ``phone``, ``profile_name``.
    ``profile_name`` is flattened here rather than exposing the
    Django ORM lookup path (``entity__profile__name``) so templates
    and JS consumers don't need to know the teams app's internal
    schema.
    """
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "profile_name": row["entity__profile__name"],
        }
        for row in (
            ContactProfileContact.objects.filter(
                entity__profile__team=team,
                entity__profile__is_component_private=False,
            )
            .order_by("entity__profile__name", "name")
            .values("id", "name", "email", "phone", "entity__profile__name")
        )
    ]


def contact_belongs_to_team(contact_id: object, team: Team) -> bool:
    """True iff ``contact_id`` identifies a ContactProfileContact in ``team``.

    Typed ``object`` deliberately — callers deserialise ``contact_id``
    from request JSON where the runtime type is not guaranteed. The
    isinstance guard rejects ``None``, empty strings, and non-string
    payloads (``{"support_contact_id": null}``, ``["abc"]``,
    ``{"id": "x"}``) up front so a malformed body resolves cleanly to
    "not a valid contact" instead of hitting ``.filter(id=<non-str>)``
    or an ORM type-coercion error.
    """
    if not isinstance(contact_id, str) or not contact_id:
        return False
    return ContactProfileContact.objects.filter(
        id=contact_id,
        entity__profile__team=team,
    ).exists()
