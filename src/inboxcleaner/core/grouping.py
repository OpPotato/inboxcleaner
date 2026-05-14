import re
from dataclasses import dataclass

from inboxcleaner.core.models import Sender, SenderGroup

_SUFFIXES = ("newsletter", "team", "support", "notifications", "news")
_SUFFIX_RE = re.compile(
    r"\s+(" + "|".join(_SUFFIXES) + r")$", re.IGNORECASE
)


def normalize_display_name(name: str | None) -> str:
    if not name:
        return ""
    s = name.strip().lower()
    # Strip one trailing suffix word (e.g. "Uniqlo Newsletter" -> "uniqlo")
    s = _SUFFIX_RE.sub("", s).strip()
    return s


@dataclass(frozen=True)
class ExistingGroup:
    group_id: int


@dataclass(frozen=True)
class NewGroup:
    name: str


GroupAssignment = ExistingGroup | NewGroup


@dataclass(frozen=True)
class GroupIndex:
    groups: list[SenderGroup]
    senders: list[Sender]


def assign_group(sender: Sender, idx: GroupIndex) -> GroupAssignment:
    norm = normalize_display_name(sender.display_name)

    # Rule 1: normalized display-name match against any sender already in a group.
    if norm:
        for existing in idx.senders:
            if existing.group_id is None:
                continue
            if normalize_display_name(existing.display_name) == norm:
                return ExistingGroup(group_id=existing.group_id)

    # Rule 2: registered-domain match.
    for existing in idx.senders:
        if existing.group_id is None:
            continue
        if existing.domain == sender.domain:
            return ExistingGroup(group_id=existing.group_id)

    # Rule 3: new group, name from display name (raw) or domain fallback.
    name = sender.display_name.strip() if sender.display_name else sender.domain
    return NewGroup(name=name)
