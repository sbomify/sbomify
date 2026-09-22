"""Owner-level invitation notices."""

import pytest
from django.core import mail

from sbomify.apps.teams.models import Member, Team
from sbomify.apps.teams.services.member_notifications import notify_owners_of_owner_invitation


@pytest.fixture
def team(db):
    return Team.objects.create(name="Notice Workspace")


def _member(django_user_model, team, username, role):
    user = django_user_model.objects.create_user(
        username=username, email=f"{username}@test.com", password="password"
    )
    Member.objects.create(user=user, team=team, role=role)
    return user


class TestOwnerInvitationNotice:
    def test_each_owner_gets_their_own_message(self, django_user_model, team):
        """One message per recipient — never one message addressed to all owners.

        A single message would carry the whole owner roster in the To: header of
        every copy, disclosing it to each recipient. This is a security notice,
        so its recipient list is exactly the thing not to broadcast.
        """
        _member(django_user_model, team, "owner1", "owner")
        _member(django_user_model, team, "owner2", "owner")
        actor = _member(django_user_model, team, "admin1", "admin")

        mail.outbox = []
        notify_owners_of_owner_invitation(team, actor, "newowner@example.com")

        assert len(mail.outbox) == 2
        for message in mail.outbox:
            assert len(message.to) == 1
        assert sorted(m.to[0] for m in mail.outbox) == ["owner1@test.com", "owner2@test.com"]

    def test_the_actor_is_not_notified_of_their_own_action(self, django_user_model, team):
        _member(django_user_model, team, "owner1", "owner")
        actor = _member(django_user_model, team, "owner2", "owner")

        mail.outbox = []
        notify_owners_of_owner_invitation(team, actor, "newowner@example.com")

        assert [m.to[0] for m in mail.outbox] == ["owner1@test.com"]

    def test_one_failed_send_does_not_silence_the_rest(self, django_user_model, team, monkeypatch):
        """A failure must not roll back the invite, nor drop the other owners."""
        _member(django_user_model, team, "owner1", "owner")
        _member(django_user_model, team, "owner2", "owner")
        actor = _member(django_user_model, team, "admin1", "admin")

        sent: list[str] = []
        real_send = mail.EmailMultiAlternatives.send

        def flaky_send(self, *args, **kwargs):
            if self.to == ["owner1@test.com"]:
                raise OSError("smtp down")
            sent.append(self.to[0])
            return real_send(self, *args, **kwargs)

        monkeypatch.setattr(mail.EmailMultiAlternatives, "send", flaky_send)

        notify_owners_of_owner_invitation(team, actor, "newowner@example.com")

        assert sent == ["owner2@test.com"]

    def test_no_owners_to_notify_is_not_an_error(self, django_user_model, team):
        actor = _member(django_user_model, team, "admin1", "admin")

        mail.outbox = []
        notify_owners_of_owner_invitation(team, actor, "newowner@example.com")

        assert mail.outbox == []
