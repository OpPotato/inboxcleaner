import pytest

from inboxcleaner.core.grouping import (
    ExistingGroup,
    GroupIndex,
    NewGroup,
    assign_group,
    normalize_display_name,
)
from inboxcleaner.core.models import Sender, SenderGroup


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Uniqlo", "uniqlo"),
        ("UNIQLO", "uniqlo"),
        ("Uniqlo Newsletter", "uniqlo"),
        ("Uniqlo Team", "uniqlo"),
        ("Uniqlo Notifications", "uniqlo"),
        ("Uniqlo News", "uniqlo"),
        ("Uniqlo Support", "uniqlo"),
        ("  Uniqlo  ", "uniqlo"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_display_name(raw, expected):
    assert normalize_display_name(raw) == expected


def test_new_sender_no_existing_groups_creates_new():
    idx = GroupIndex(groups=[], senders=[])
    s = Sender(email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com")
    result = assign_group(s, idx)
    assert isinstance(result, NewGroup)
    assert result.name == "Uniqlo"


def test_matches_existing_group_by_domain():
    g = SenderGroup(id=1, name="Uniqlo", created_by="auto")
    s_existing = Sender(
        id=10, email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=1
    )
    idx = GroupIndex(groups=[g], senders=[s_existing])

    new_sender = Sender(
        email="noreply@email.uniqlo.com",
        display_name="Uniqlo Newsletter",
        domain="uniqlo.com",
    )
    result = assign_group(new_sender, idx)
    assert isinstance(result, ExistingGroup)
    assert result.group_id == 1


def test_matches_existing_group_by_display_name_even_when_domain_differs():
    """ESP-relayed mail: 'bounces@sendgrid.net' display 'Uniqlo' should join existing group."""
    g = SenderGroup(id=1, name="Uniqlo", created_by="auto")
    s_existing = Sender(
        id=10, email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=1
    )
    idx = GroupIndex(groups=[g], senders=[s_existing])

    esp_sender = Sender(
        email="bounces@sendgrid.net",
        display_name="Uniqlo",
        domain="sendgrid.net",
    )
    result = assign_group(esp_sender, idx)
    assert isinstance(result, ExistingGroup)
    assert result.group_id == 1


def test_display_name_normalization_treats_variants_as_same():
    g = SenderGroup(id=1, name="Uniqlo", created_by="auto")
    s_existing = Sender(
        id=10, email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=1
    )
    idx = GroupIndex(groups=[g], senders=[s_existing])

    variant = Sender(
        email="contact@other-domain.net",
        display_name="UNIQLO Newsletter",
        domain="other-domain.net",
    )
    result = assign_group(variant, idx)
    assert isinstance(result, ExistingGroup)
    assert result.group_id == 1


def test_missing_display_name_falls_back_to_domain_name():
    idx = GroupIndex(groups=[], senders=[])
    s = Sender(email="noreply@example.com", display_name=None, domain="example.com")
    result = assign_group(s, idx)
    assert isinstance(result, NewGroup)
    assert result.name == "example.com"
