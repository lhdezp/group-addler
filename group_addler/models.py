from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AddStatus(str, Enum):
    """Outcome of a single participant add attempt."""

    ADDED = "added"
    ALREADY_MEMBER = "already_member"
    FAILED = "failed"


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    member_count: int
    is_admin: bool
    jid: Any


@dataclass(frozen=True)
class Member:
    """A group participant.

    WhatsApp can report the same person with a phone-number identifier (PN) or
    a hidden identifier (LID). Keeping every known identifier lets selection
    work across groups that use different addressing modes.
    """

    user_id: str
    jid: Any = None
    is_lid: bool = False
    pn: str = ""
    lid: str = ""
    pn_jid: Any = None
    lid_jid: Any = None
    display_name: str = ""

    def identities(self) -> set[str]:
        return {value for value in (self.user_id, self.pn, self.lid) if value}

    @property
    def label(self) -> str:
        return self.display_name or self.pn or self.lid or self.user_id or "-"

    def with_phone(self, pn: str, pn_jid: Any) -> Member:
        """Return a copy of this member enriched with its phone number."""
        return Member(
            user_id=pn or self.user_id,
            jid=self.jid,
            is_lid=self.is_lid,
            pn=pn,
            lid=self.lid,
            pn_jid=pn_jid,
            lid_jid=self.lid_jid,
            display_name=self.display_name,
        )


def select_members_to_add(
    source_members: Iterable[Member],
    target_members: Iterable[Member],
    my_user_ids: Iterable[str] | None = None,
) -> list[Member]:
    """Return source members that are not in the target group nor the current user.

    Matching is done on every known identity (phone number, LID and canonical
    user id) so that a group listing LIDs and a group listing phone numbers do
    not produce duplicate add attempts.
    """
    blocked: set[str] = {value for value in (my_user_ids or ()) if value}
    for member in target_members:
        blocked |= member.identities()

    selected: list[Member] = []
    for member in source_members:
        identities = member.identities()
        if not identities or identities & blocked:
            continue
        blocked |= identities
        selected.append(member)

    return selected
