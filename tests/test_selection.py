import unittest

from group_addler.models import Member, select_members_to_add


class SelectMembersToAddTests(unittest.TestCase):
    def test_excludes_self_and_existing_members(self) -> None:
        source = [
            Member("111", jid="111@s.whatsapp.net"),
            Member("222", jid="222@s.whatsapp.net"),
            Member("333", jid="333@s.whatsapp.net"),
        ]
        target = [Member("222", jid="222@s.whatsapp.net")]

        selected = select_members_to_add(source, target, my_user_ids=["111"])

        self.assertEqual([member.user_id for member in selected], ["333"])

    def test_deduplicates_source_members(self) -> None:
        source = [
            Member("222", jid="222@s.whatsapp.net"),
            Member("222", jid="222@s.whatsapp.net"),
            Member("333", jid="333@s.whatsapp.net"),
        ]

        selected = select_members_to_add(source, [], my_user_ids=["111"])

        self.assertEqual([member.user_id for member in selected], ["222", "333"])

    def test_ignores_members_without_identifiers(self) -> None:
        source = [Member("", jid=""), Member("222", jid="222@s.whatsapp.net")]

        selected = select_members_to_add(source, [], my_user_ids=None)

        self.assertEqual([member.user_id for member in selected], ["222"])

    def test_returns_empty_when_everyone_is_in_target(self) -> None:
        members = [Member("222", jid="222@s.whatsapp.net", pn="222")]

        selected = select_members_to_add(members, members, my_user_ids=["111"])

        self.assertEqual(selected, [])

    def test_matches_phone_number_against_lid_member(self) -> None:
        source = [
            Member("999", jid="999@lid", is_lid=True, pn="54911", lid="999"),
        ]
        target = [Member("54911", jid="54911@s.whatsapp.net", pn="54911")]

        selected = select_members_to_add(source, target, my_user_ids=[])

        self.assertEqual(selected, [])

    def test_matches_existing_member_reported_only_by_lid(self) -> None:
        source = [Member("54911", pn="54911")]
        target = [Member("999", is_lid=True, lid="999")]

        selected = select_members_to_add(source, target, my_user_ids=[])

        self.assertEqual([member.user_id for member in selected], ["54911"])

    def test_excludes_self_when_reported_as_lid(self) -> None:
        source = [
            Member("888", is_lid=True, lid="888"),
            Member("222", pn="222"),
        ]

        selected = select_members_to_add(
            source, [], my_user_ids=["111", "888"]
        )

        self.assertEqual([member.user_id for member in selected], ["222"])

    def test_deduplicates_members_reported_in_both_modes(self) -> None:
        source = [
            Member("999", lid="999"),
            Member("54911", pn="54911", lid="999"),
        ]

        selected = select_members_to_add(source, [], my_user_ids=[])

        self.assertEqual(len(selected), 1)


if __name__ == "__main__":
    unittest.main()
