from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from group_addler import service as service_module
from group_addler.limits import UsageLimiter, get_policy
from group_addler.models import AddStatus, Group, Member
from group_addler.service import AddProgress, ConnectionState, WhatsAppService


class FakeJID:
    """Minimal stand-in for neonize's JID protobuf message."""

    def __init__(self, user: str, server: str = "s.whatsapp.net", device: int = 0):
        self.User = user
        self.Server = server
        self.Device = device


class FakeParticipant:
    def __init__(
        self,
        user: str,
        server: str = "s.whatsapp.net",
        *,
        phone: str | None = None,
        lid: str | None = None,
        admin: bool = False,
        display_name: str = "",
    ):
        self.JID = FakeJID(user, server)
        self.PhoneNumber = FakeJID(phone) if phone else None
        self.LID = FakeJID(lid, "lid") if lid else None
        self.IsAdmin = admin
        self.IsSuperAdmin = False
        self.DisplayName = display_name


class FakeGroupName:
    def __init__(self, name: str):
        self.Name = name


class FakeRawGroup:
    def __init__(self, jid: FakeJID, name: str, participants: list):
        self.JID = jid
        self.GroupName = FakeGroupName(name)
        self.Participants = participants

    def HasField(self, field: str) -> bool:
        return field == "GroupName"


class FakeAddResult:
    def __init__(self, error: int):
        self.Error = error


class FakeClient:
    def __init__(self) -> None:
        self.groups: dict[str, FakeRawGroup] = {}
        self.pn_by_lid: dict[str, FakeJID] = {}
        self.add_responses: list[list[FakeAddResult]] = []
        self.add_calls: list[tuple[FakeJID, FakeJID]] = []

    def get_group_info(self, jid: FakeJID) -> FakeRawGroup:
        return self.groups[jid.User]

    def get_pn_from_lid(self, jid: FakeJID) -> FakeJID:
        return self.pn_by_lid[jid.User]

    def update_group_participants(self, jid, participants, _action):
        self.add_calls.append((jid, participants[0]))
        if self.add_responses:
            return self.add_responses.pop(0)
        return [FakeAddResult(200)]


def make_service(client: FakeClient, **kwargs) -> WhatsAppService:
    service = WhatsAppService("test-session", **kwargs)
    service._client = client
    return service


def make_group(name: str, participants: int = 1) -> Group:
    return Group(
        id=f"{name}@g.us",
        name=name,
        member_count=participants,
        is_admin=True,
        jid=FakeJID(name, "g.us"),
    )


class ParseGroupTests(unittest.TestCase):
    def test_detects_admin_by_lid_identity(self) -> None:
        raw = FakeRawGroup(
            FakeJID("123", "g.us"),
            "Equipo",
            [
                FakeParticipant("900", "lid", lid="900", admin=True),
                FakeParticipant("555"),
            ],
        )
        service = make_service(FakeClient())
        service._my_ids = {"900"}

        group = service._parse_group(raw)

        self.assertTrue(group.is_admin)
        self.assertEqual(group.member_count, 2)
        self.assertEqual(group.name, "Equipo")

    def test_not_admin_when_only_other_member_is_admin(self) -> None:
        raw = FakeRawGroup(
            FakeJID("123", "g.us"),
            "Equipo",
            [FakeParticipant("555", admin=True), FakeParticipant("777")],
        )
        service = make_service(FakeClient())
        service._my_ids = {"777"}

        self.assertFalse(service._parse_group(raw).is_admin)

    def test_uses_placeholder_name_without_group_name(self) -> None:
        raw = FakeRawGroup(FakeJID("123", "g.us"), "", [])
        service = make_service(FakeClient())

        self.assertEqual(service._parse_group(raw).name, "Sin nombre")


class PlanAddTests(unittest.IsolatedAsyncioTestCase):
    async def test_excludes_existing_members_and_self(self) -> None:
        client = FakeClient()
        client.groups["source"] = FakeRawGroup(
            FakeJID("source", "g.us"),
            "Origen",
            [
                FakeParticipant("111"),
                FakeParticipant("222"),
                FakeParticipant("333"),
            ],
        )
        client.groups["target"] = FakeRawGroup(
            FakeJID("target", "g.us"),
            "Destino",
            [FakeParticipant("222")],
        )
        service = make_service(client)
        service._my_ids = {"111"}

        plan = await service.plan_add(
            make_group("source", 3), make_group("target", 1)
        )

        self.assertEqual([member.user_id for member in plan], ["333"])

    async def test_resolves_lid_to_phone_before_selection(self) -> None:
        client = FakeClient()
        client.groups["source"] = FakeRawGroup(
            FakeJID("source", "g.us"),
            "Origen",
            [FakeParticipant("900", "lid", lid="900")],
        )
        client.groups["target"] = FakeRawGroup(
            FakeJID("target", "g.us"),
            "Destino",
            [FakeParticipant("54911")],
        )
        client.pn_by_lid["900"] = FakeJID("54911")
        service = make_service(client)
        service._my_ids = set()

        plan = await service.plan_add(make_group("source"), make_group("target"))

        self.assertEqual(plan, [])

    async def test_raises_when_target_members_cannot_be_read(self) -> None:
        client = FakeClient()
        client.groups["source"] = FakeRawGroup(
            FakeJID("source", "g.us"), "Origen", [FakeParticipant("222")]
        )
        client.groups["target"] = FakeRawGroup(
            FakeJID("target", "g.us"), "Destino", []
        )
        service = make_service(client)

        with self.assertRaises(RuntimeError):
            await service.plan_add(make_group("source"), make_group("target", 5))


class TryAddTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.service = make_service(self.client)
        self.target = make_group("target")
        self._original_action = service_module._add_action
        service_module._add_action = lambda: "ADD"

    def tearDown(self) -> None:
        service_module._add_action = self._original_action

    def test_reports_success(self) -> None:
        self.client.add_responses.append([FakeAddResult(200)])

        status, _ = self.service._try_add(self.target, FakeJID("222"))

        self.assertIs(status, AddStatus.ADDED)

    def test_reports_already_member(self) -> None:
        self.client.add_responses.append([FakeAddResult(409)])

        status, detail = self.service._try_add(self.target, FakeJID("222"))

        self.assertIs(status, AddStatus.ALREADY_MEMBER)
        self.assertIn("ya era miembro", detail)

    def test_reports_failure_code(self) -> None:
        self.client.add_responses.append([FakeAddResult(403)])

        status, detail = self.service._try_add(self.target, FakeJID("222"))

        self.assertIs(status, AddStatus.FAILED)
        self.assertIn("403", detail)

    def test_empty_response_is_not_reported_as_success(self) -> None:
        self.client.add_responses.append([])

        status, detail = self.service._try_add(self.target, FakeJID("222"))

        self.assertIs(status, AddStatus.FAILED)
        self.assertIn("confirmacion", detail)

    def test_reports_exception_as_failure(self) -> None:
        def boom(*_args, **_kwargs):
            raise ValueError("boom")

        self.client.update_group_participants = boom

        status, detail = self.service._try_add(self.target, FakeJID("222"))

        self.assertIs(status, AddStatus.FAILED)
        self.assertIn("boom", detail)


class AddParticipantsTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_each_outcome(self) -> None:
        client = FakeClient()
        client.add_responses = [
            [FakeAddResult(200)],
            [FakeAddResult(409)],
            [FakeAddResult(403)],
        ]
        service = make_service(client, add_delay=0, batch_pause=0)
        target = make_group("target")
        members = [
            Member("1", jid=FakeJID("1")),
            Member("2", jid=FakeJID("2")),
            Member("3", jid=FakeJID("3")),
        ]
        progress: list[AddProgress] = []
        original_action = service_module._add_action
        service_module._add_action = lambda: "ADD"
        try:
            summary = await service.add_participants(
                target, members, on_progress=progress.append
            )
        finally:
            service_module._add_action = original_action

        self.assertEqual((summary.added, summary.skipped, summary.failed), (1, 1, 1))
        self.assertFalse(summary.cancelled)
        self.assertEqual(summary.total, 3)
        self.assertEqual([step.processed for step in progress], [1, 2, 3])
        self.assertEqual(len(summary.results), 3)

    async def test_stops_when_cancelled(self) -> None:
        client = FakeClient()
        service = make_service(client, add_delay=0, batch_pause=0)
        target = make_group("target")
        members = [Member(str(i), jid=FakeJID(str(i))) for i in range(1, 6)]
        cancel = asyncio.Event()

        def on_progress(_progress: AddProgress) -> None:
            cancel.set()

        original_action = service_module._add_action
        service_module._add_action = lambda: "ADD"
        try:
            summary = await service.add_participants(
                target, members, on_progress=on_progress, cancel=cancel
            )
        finally:
            service_module._add_action = original_action

        self.assertTrue(summary.cancelled)
        self.assertEqual(summary.added, 1)
        self.assertEqual(len(summary.results), 1)

    async def test_stops_after_repeated_failures(self) -> None:
        client = FakeClient()
        client.add_responses = [[FakeAddResult(403)] for _ in range(5)]
        service = make_service(client, add_delay=0, batch_pause=0)
        target = make_group("target")
        members = [Member(str(i), jid=FakeJID(str(i))) for i in range(1, 6)]

        original_action = service_module._add_action
        service_module._add_action = lambda: "ADD"
        try:
            summary = await service.add_participants(target, members)
        finally:
            service_module._add_action = original_action

        self.assertTrue(summary.cancelled)
        self.assertIn("fallos seguidos", summary.abort_reason)
        self.assertEqual(
            len(summary.results), service_module.MAX_CONSECUTIVE_FAILURES
        )

    async def test_stops_on_rate_limit_code(self) -> None:
        client = FakeClient()
        client.add_responses = [
            [FakeAddResult(200)],
            [FakeAddResult(429)],
            [FakeAddResult(200)],
        ]
        service = make_service(client, add_delay=0, batch_pause=0)
        target = make_group("target")
        members = [Member(str(i), jid=FakeJID(str(i))) for i in range(1, 4)]

        original_action = service_module._add_action
        service_module._add_action = lambda: "ADD"
        try:
            summary = await service.add_participants(target, members)
        finally:
            service_module._add_action = original_action

        self.assertTrue(summary.cancelled)
        self.assertIn("429", summary.abort_reason)
        self.assertEqual(len(summary.results), 2)

    async def test_aborts_when_account_is_restricted(self) -> None:
        service = make_service(FakeClient(), add_delay=0, batch_pause=0)
        target = make_group("target")
        members = [Member("1", jid=FakeJID("1"))]

        service._abort("cuenta restringida")

        summary = await service.add_participants(target, members)

        self.assertTrue(summary.cancelled)
        self.assertEqual(summary.abort_reason, "cuenta restringida")
        self.assertEqual(summary.results, ())

    async def test_respects_hourly_cap_and_records_usage(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        limiter = UsageLimiter(Path(tmp.name) / "rate-limit.json")
        policy = replace(
            get_policy("cauto"),
            hourly_cap=1,
            daily_cap=10,
            cooldown=0,
        )
        client = FakeClient()
        service = make_service(
            client,
            add_delay=0,
            batch_pause=0,
            policy=policy,
            limiter=limiter,
        )
        target = make_group("target")
        members = [Member("1", jid=FakeJID("1")), Member("2", jid=FakeJID("2"))]

        original_action = service_module._add_action
        service_module._add_action = lambda: "ADD"
        try:
            summary = await service.add_participants(target, members)
        finally:
            service_module._add_action = original_action

        self.assertTrue(summary.cancelled)
        self.assertIn("Limite por hora", summary.abort_reason)
        self.assertEqual(len(summary.results), 1)
        self.assertEqual(len(client.add_calls), 1)
        self.assertEqual(limiter.remaining_this_hour(policy), 0)

    async def test_falls_back_to_phone_when_lid_add_fails(self) -> None:
        client = FakeClient()
        service = make_service(client, add_delay=0)
        target = make_group("target")
        member = Member("900", is_lid=True, lid="900", lid_jid=FakeJID("900", "lid"))
        calls: list[object] = []

        def fake_try_add(_target: Group, jid) -> tuple[AddStatus, str]:
            calls.append(jid)
            if len(calls) == 1:
                return AddStatus.FAILED, "codigo 401"
            return AddStatus.ADDED, ""

        service._try_add = fake_try_add
        service._resolve_pn_jid = lambda _member: FakeJID("54911")

        status, _ = await service._add_member(target, member)

        self.assertIs(status, AddStatus.ADDED)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].User, "54911")

    async def test_fails_when_lid_cannot_be_resolved(self) -> None:
        service = make_service(FakeClient(), add_delay=0)
        target = make_group("target")
        member = Member("900", is_lid=True, lid="900", lid_jid=FakeJID("900", "lid"))
        service._try_add = lambda *_args: (AddStatus.FAILED, "codigo 401")
        service._resolve_pn_jid = lambda _member: None

        status, detail = await service._add_member(target, member)

        self.assertIs(status, AddStatus.FAILED)
        self.assertIn("LID", detail)


class SnapshotTests(unittest.TestCase):
    def test_default_snapshot_is_connecting(self) -> None:
        snapshot = make_service(FakeClient()).snapshot()

        self.assertIs(snapshot.state, ConnectionState.CONNECTING)
        self.assertIsNone(snapshot.qr_data_uri)

    def test_qr_updates_bump_version(self) -> None:
        service = make_service(FakeClient())
        service._qr_data_uri = "data:image/png;base64,aaa"
        service._qr_version = 2
        service._state = ConnectionState.WAITING_QR

        snapshot = service.snapshot()

        self.assertEqual(snapshot.qr_version, 2)
        self.assertEqual(snapshot.qr_data_uri, "data:image/png;base64,aaa")


if __name__ == "__main__":
    unittest.main()
