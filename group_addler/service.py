from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any

from .limits import RatePolicy, UsageLimiter, default_policy
from .models import AddStatus, Group, Member, select_members_to_add

if TYPE_CHECKING:
    from neonize.client import NewClient

logger = logging.getLogger(__name__)

LOGIN_TIMEOUT_SECONDS = 180.0

# Abort the run when WhatsApp clearly signals that it is throttling us.
_RATE_LIMIT_CODES = {429}
# Several failures in a row usually mean the account is being restricted.
MAX_CONSECUTIVE_FAILURES = 3

# Per-participant result codes reported by WhatsApp.
_STATUS_OK = 200
_STATUS_ALREADY_MEMBER = 409

_TEMP_BAN_REASONS = {
    1: "demasiados envios a personas nuevas",
    2: "bloqueado por usuarios",
    3: "demasiados grupos creados",
    4: "mismo mensaje enviado a demasiadas personas",
    5: "lista de difusion",
}


class ConnectionState(str, Enum):
    CONNECTING = "connecting"
    WAITING_QR = "waiting_qr"
    READY = "ready"
    FAILED = "failed"
    LOGGED_OUT = "logged_out"


@dataclass(frozen=True)
class ConnectionSnapshot:
    state: ConnectionState
    message: str = ""
    qr_data_uri: str | None = None
    qr_version: int = 0


@dataclass(frozen=True)
class AddProgress:
    processed: int
    total: int
    added: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class AddResult:
    member: Member
    status: AddStatus
    detail: str = ""


@dataclass(frozen=True)
class AddSummary:
    total: int
    added: int
    skipped: int
    failed: int
    cancelled: bool
    results: tuple[AddResult, ...]
    abort_reason: str = ""

    def export_rows(self) -> list[list[str]]:
        rows = [
            [
                "nombre",
                "identificador",
                "telefono",
                "lid",
                "resultado",
                "detalle",
            ]
        ]
        for result in self.results:
            rows.append(
                [
                    result.member.label,
                    result.member.user_id,
                    result.member.pn,
                    result.member.lid,
                    result.status.value,
                    result.detail,
                ]
            )
        return rows


def _jid_user(jid: Any) -> str:
    return str(getattr(jid, "User", "") or "")


def _jid_server(jid: Any) -> str:
    return str(getattr(jid, "Server", "") or "")


def _jid_is_lid(jid: Any) -> bool:
    return _jid_server(jid) == "lid"


def _jid_to_string(jid: Any) -> str:
    user = _jid_user(jid)
    server = _jid_server(jid)
    if not user:
        return server
    device = int(getattr(jid, "Device", 0) or 0)
    return f"{user}:{device}@{server}" if device else f"{user}@{server}"


def _build_jid(user: str, server: str = "s.whatsapp.net") -> Any:
    from neonize.utils.jid import build_jid

    return build_jid(user, server)


def _add_action() -> Any:
    """Return the neonize enum value used to request an add.

    Kept behind a function so importing this module (for example from tests)
    never requires neonize to be installed.
    """
    from neonize.utils.enum import ParticipantChange

    return ParticipantChange.ADD


def _qr_data_uri(data: bytes) -> str:
    import segno

    buffer = io.BytesIO()
    segno.make(data.decode("utf-8", errors="replace")).save(
        buffer, kind="png", scale=8, border=3
    )
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _with_overrides(
    policy: RatePolicy,
    *,
    add_delay: float | None,
    batch_size: int | None,
    batch_pause: float | None,
) -> RatePolicy:
    """Pin delays/batch size when a caller passes explicit values."""
    changes: dict[str, Any] = {}
    if add_delay is not None:
        fixed = max(0.0, add_delay)
        changes["min_delay"] = fixed
        changes["max_delay"] = fixed
    if batch_pause is not None:
        fixed = max(0.0, batch_pause)
        changes["batch_pause_min"] = fixed
        changes["batch_pause_max"] = fixed
    if batch_size is not None:
        changes["batch_size"] = max(1, batch_size)
    if not changes:
        return policy
    return replace(policy, **changes)


class WhatsAppService:
    def __init__(
        self,
        session_path: str,
        add_delay: float | None = None,
        batch_size: int | None = None,
        batch_pause: float | None = None,
        policy: RatePolicy | None = None,
        limiter: UsageLimiter | None = None,
    ):
        self.session_path = session_path
        self.policy = _with_overrides(
            policy or default_policy(),
            add_delay=add_delay,
            batch_size=batch_size,
            batch_pause=batch_pause,
        )
        self.limiter = limiter

        self._client: NewClient | None = None
        self._lock = threading.Lock()
        self._state = ConnectionState.CONNECTING
        self._message = "Conectando con WhatsApp..."
        self._qr_data_uri: str | None = None
        self._qr_version = 0
        self._my_ids: set[str] = set()
        self._pn_cache: dict[str, Any | None] = {}
        self._abort_event = threading.Event()
        self._abort_message = ""
        self._last_error_code = 0

    def set_policy(self, policy: RatePolicy) -> None:
        """Replace the pacing policy used by the next run."""
        self.policy = policy

    # ------------------------------------------------------------------ setup

    def start(self) -> None:
        from neonize.client import NewClient
        from neonize.events import (
            ConnectedEv,
            ConnectFailureEv,
            DisconnectedEv,
            LoggedOutEv,
            TemporaryBanEv,
        )

        client = NewClient(self.session_path)
        client.event(ConnectedEv)(self._on_connected)
        client.event(ConnectFailureEv)(self._on_connect_failure)
        client.event(DisconnectedEv)(self._on_disconnected)
        client.event(LoggedOutEv)(self._on_logged_out)
        client.event(TemporaryBanEv)(self._on_temporary_ban)
        client.event.qr(self._on_qr)

        self._client = client
        threading.Thread(
            target=self._connect,
            name="whatsapp-connect",
            daemon=True,
        ).start()

    def stop(self) -> None:
        self._abort_event.set()
        with self._lock:
            client, self._client = self._client, None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            logger.debug("Could not disconnect WhatsApp client", exc_info=True)

    def _abort(self, message: str) -> None:
        """Ask a running add loop to stop after the request in flight."""
        with self._lock:
            self._abort_message = message
        self._abort_event.set()

    def _stop_reason(self) -> str:
        if not self._abort_event.is_set():
            return ""
        with self._lock:
            return self._abort_message or "Se detuvo la operacion."

    @property
    def client(self) -> NewClient:
        if self._client is None:
            raise RuntimeError("WhatsApp client has not been started")
        return self._client

    # ------------------------------------------------------------------ state

    def snapshot(self) -> ConnectionSnapshot:
        with self._lock:
            return ConnectionSnapshot(
                state=self._state,
                message=self._message,
                qr_data_uri=self._qr_data_uri,
                qr_version=self._qr_version,
            )

    def _set_state(self, state: ConnectionState, message: str = "") -> None:
        with self._lock:
            self._state = state
            self._message = message
        logger.info("WhatsApp state: %s (%s)", state.value, message)

    def _connect(self) -> None:
        try:
            self.client.connect()
        except Exception:
            logger.exception("WhatsApp connection failed")
            self._set_state(
                ConnectionState.FAILED,
                "No se pudo conectar con WhatsApp. Revisa la conexion a internet.",
            )

    # ----------------------------------------------------------------- events

    def _on_connected(self, client: NewClient, event: Any) -> None:
        try:
            if not bool(getattr(event, "status", True)):
                return

            me = getattr(client, "me", None)
            if me is None:
                logger.warning("Connected event received without device info")
                self._set_state(
                    ConnectionState.FAILED,
                    "No se pudo identificar la cuenta de WhatsApp.",
                )
                return

            my_ids: set[str] = set()
            for jid in (getattr(me, "JID", None), getattr(me, "LID", None)):
                user = _jid_user(jid)
                if user:
                    my_ids.add(user)

            with self._lock:
                self._my_ids = my_ids
                self._state = ConnectionState.READY
                self._message = "Conectado"
                self._qr_data_uri = None

            self._abort_event.clear()
            logger.info("Connected as %s", ", ".join(sorted(my_ids)))
        except Exception:
            logger.exception("Error while handling connected event")

    def _on_qr(self, _client: NewClient, data: bytes) -> None:
        try:
            data_uri = _qr_data_uri(data)
        except Exception:
            logger.exception("Failed to render QR code")
            self._set_state(
                ConnectionState.FAILED,
                "No se pudo generar el codigo QR.",
            )
            return

        with self._lock:
            self._qr_data_uri = data_uri
            self._qr_version += 1
            self._state = ConnectionState.WAITING_QR
            self._message = "Escanea el codigo QR desde WhatsApp"

    def _on_connect_failure(self, _client: NewClient, event: Any) -> None:
        message = str(getattr(event, "Message", "") or "").strip()
        if not message:
            message = f"No se pudo conectar (motivo {getattr(event, 'Reason', '?')})"
        self._set_state(ConnectionState.FAILED, message)

    def _on_disconnected(self, _client: NewClient, _event: Any) -> None:
        with self._lock:
            was_ready = self._state is ConnectionState.READY
        if not was_ready:
            return
        self._set_state(
            ConnectionState.CONNECTING,
            "Conexion perdida. Reintentando...",
        )

    def _on_logged_out(self, _client: NewClient, _event: Any) -> None:
        self._set_state(
            ConnectionState.LOGGED_OUT,
            "La sesion de WhatsApp se cerro. Escanea el QR de nuevo.",
        )
        self._abort("La sesion de WhatsApp se cerro.")

    def _on_temporary_ban(self, _client: NewClient, event: Any) -> None:
        code = int(getattr(event, "Code", 0) or 0)
        reason = _TEMP_BAN_REASONS.get(code, f"motivo {code}")
        expire = int(getattr(event, "Expire", 0) or 0)
        if expire:
            until = time.strftime("%Y-%m-%d %H:%M", time.localtime(expire))
            self._set_state(
                ConnectionState.FAILED,
                f"WhatsApp restringio la cuenta ({reason}) hasta {until}.",
            )
        else:
            self._set_state(
                ConnectionState.FAILED,
                f"WhatsApp restringio la cuenta ({reason}).",
            )
        self._abort(f"WhatsApp restringio la cuenta ({reason}).")

    # ----------------------------------------------------------------- groups

    def get_groups(self) -> list[Group]:
        groups: list[Group] = []
        for raw_group in self.client.get_joined_groups():
            try:
                groups.append(self._parse_group(raw_group))
            except Exception:
                logger.exception("Failed to parse group")
        logger.info("Loaded %d groups", len(groups))
        return groups

    def _parse_group(self, raw_group: Any) -> Group:
        name = "Sin nombre"
        if raw_group.HasField("GroupName"):
            name = raw_group.GroupName.Name or "Sin nombre"

        participants = list(raw_group.Participants)
        is_admin = any(
            self._is_admin(participant)
            and bool(self._participant_ids(participant) & self._my_ids)
            for participant in participants
        )

        return Group(
            id=_jid_to_string(raw_group.JID),
            name=name,
            member_count=len(participants),
            is_admin=is_admin,
            jid=raw_group.JID,
        )

    @staticmethod
    def _is_admin(participant: Any) -> bool:
        return bool(
            getattr(participant, "IsAdmin", False)
            or getattr(participant, "IsSuperAdmin", False)
        )

    @staticmethod
    def _participant_ids(participant: Any) -> set[str]:
        ids = set()
        for jid in (
            getattr(participant, "JID", None),
            getattr(participant, "LID", None),
            getattr(participant, "PhoneNumber", None),
        ):
            user = _jid_user(jid)
            if user:
                ids.add(user)
        return ids

    # ---------------------------------------------------------------- members

    def _parse_member(self, participant: Any) -> Member:
        jid = getattr(participant, "JID", None)
        phone = getattr(participant, "PhoneNumber", None)
        lid_field = getattr(participant, "LID", None)

        is_lid = _jid_is_lid(jid)
        phone_user = "" if _jid_is_lid(phone) else _jid_user(phone)
        lid_user = _jid_user(lid_field) or (_jid_user(jid) if is_lid else "")

        if phone_user:
            pn, pn_jid = phone_user, phone
        elif not is_lid:
            pn, pn_jid = _jid_user(jid), jid
        else:
            pn, pn_jid = "", None

        return Member(
            user_id=pn or lid_user or _jid_user(jid),
            jid=jid,
            is_lid=is_lid,
            pn=pn,
            lid=lid_user,
            pn_jid=pn_jid,
            lid_jid=jid if is_lid else lid_field,
            display_name=str(getattr(participant, "DisplayName", "") or ""),
        )

    def _members(self, group_info: Any, resolve_lids: bool = False) -> list[Member]:
        members: list[Member] = []
        for participant in group_info.Participants:
            member = self._parse_member(participant)
            if resolve_lids and not member.pn and member.lid:
                pn_jid = self._resolve_pn_jid(member)
                if pn_jid is not None:
                    member = member.with_phone(_jid_user(pn_jid), pn_jid)
            members.append(member)
        return members

    def _resolve_pn_jid(self, member: Member) -> Any | None:
        lid = member.lid
        if not lid:
            return None

        if lid in self._pn_cache:
            return self._pn_cache[lid]

        lid_jid = member.lid_jid or _build_jid(lid, "lid")
        try:
            resolved = self.client.get_pn_from_lid(lid_jid)
        except Exception:
            logger.debug("Could not resolve LID %s", lid, exc_info=True)
            self._pn_cache[lid] = None
            return None

        if not _jid_user(resolved):
            self._pn_cache[lid] = None
            return None

        self._pn_cache[lid] = resolved
        return resolved

    # ------------------------------------------------------------------ plan

    async def plan_add(self, source: Group, target: Group) -> list[Member]:
        """Return the members that would be added to the target group."""
        source_members, target_members = await asyncio.gather(
            asyncio.to_thread(self._load_members, source),
            asyncio.to_thread(self._load_members, target),
        )

        if target.member_count and not target_members:
            raise RuntimeError(
                "No se pudieron leer los miembros del grupo destino."
            )

        with self._lock:
            my_ids = set(self._my_ids)

        return select_members_to_add(source_members, target_members, my_ids)

    def _load_members(self, group: Group) -> list[Member]:
        info = self.client.get_group_info(group.jid)
        return self._members(info, resolve_lids=True)

    async def add_participants(
        self,
        target: Group,
        members: list[Member],
        on_progress: Callable[[AddProgress], None] | None = None,
        cancel: asyncio.Event | None = None,
        on_wait: Callable[[int], None] | None = None,
    ) -> AddSummary:
        total = len(members)
        added = 0
        skipped = 0
        failed = 0
        cancelled = False
        abort_reason = ""
        consecutive_failures = 0
        results: list[AddResult] = []

        logger.info("Adding %d participants to %s", total, target.name)

        for index, member in enumerate(members, start=1):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break

            stop_reason = self._stop_reason()
            if stop_reason:
                cancelled = True
                abort_reason = stop_reason
                break

            blocked = self._cap_block()
            if blocked:
                cancelled = True
                abort_reason = blocked
                break

            status, detail = await self._add_member(target, member)
            if self.limiter is not None:
                self.limiter.record()
            results.append(AddResult(member, status, detail))
            if status is AddStatus.ADDED:
                added += 1
            elif status is AddStatus.ALREADY_MEMBER:
                skipped += 1
            else:
                failed += 1
                logger.warning(
                    "Could not add %s to %s: %s",
                    member.user_id,
                    target.name,
                    detail,
                )

            if on_progress is not None:
                on_progress(AddProgress(index, total, added, skipped, failed))

            if self._last_error_code in _RATE_LIMIT_CODES:
                cancelled = True
                abort_reason = (
                    "WhatsApp limito los agregados "
                    f"(codigo {self._last_error_code}). "
                    "Espera antes de volver a intentar."
                )
                break

            if status is AddStatus.FAILED:
                consecutive_failures += 1
            else:
                consecutive_failures = 0

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                cancelled = True
                abort_reason = (
                    f"{consecutive_failures} fallos seguidos. "
                    "Se detuvo la operacion para no arriesgar la cuenta."
                )
                break

            if index < total:
                is_batch_end = index % self.policy.batch_size == 0
                if is_batch_end:
                    delay = self.policy.next_batch_pause()
                else:
                    delay = self.policy.next_delay()
                if await self._wait_or_cancel(delay, cancel, on_wait):
                    cancelled = True
                    abort_reason = self._stop_reason() or abort_reason
                    break

        if self.limiter is not None and results:
            self.limiter.mark_run_finished()

        logger.info(
            "Finished adding participants: added=%d skipped=%d failed=%d total=%d",
            added,
            skipped,
            failed,
            total,
        )
        return AddSummary(
            total=total,
            added=added,
            skipped=skipped,
            failed=failed,
            cancelled=cancelled,
            results=tuple(results),
            abort_reason=abort_reason,
        )

    def _cap_block(self) -> str:
        if self.limiter is None:
            return ""
        return self.limiter.blocked_reason(self.policy) or ""

    async def _wait_or_cancel(
        self,
        delay: float,
        cancel: asyncio.Event | None,
        on_tick: Callable[[int], None] | None = None,
    ) -> bool:
        """Wait the delay in small steps so cancel/abort feel immediate."""
        if delay <= 0:
            return False

        deadline = time.monotonic() + delay
        last_tick = -1
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._abort_event.is_set():
                return True
            if cancel is not None and cancel.is_set():
                return True

            if on_tick is not None:
                seconds = max(1, math.ceil(remaining))
                if seconds != last_tick:
                    last_tick = seconds
                    try:
                        on_tick(seconds)
                    except Exception:
                        logger.debug("Error in wait callback", exc_info=True)

            step = min(0.5, remaining)
            if cancel is None:
                await asyncio.sleep(step)
                continue
            try:
                await asyncio.wait_for(cancel.wait(), timeout=step)
            except TimeoutError:
                pass

    async def _add_member(
        self, target: Group, member: Member
    ) -> tuple[AddStatus, str]:
        status, detail = await asyncio.to_thread(self._try_add, target, member.jid)
        if status is not AddStatus.FAILED or not member.is_lid:
            return status, detail

        pn_jid = member.pn_jid
        if pn_jid is None:
            pn_jid = await asyncio.to_thread(self._resolve_pn_jid, member)
        if pn_jid is None:
            return AddStatus.FAILED, "no se pudo resolver el telefono del LID"

        return await asyncio.to_thread(self._try_add, target, pn_jid)

    def _try_add(self, target: Group, jid: Any) -> tuple[AddStatus, str]:
        try:
            response = self.client.update_group_participants(
                target.jid,
                [jid],
                _add_action(),
            )
        except Exception as exc:
            logger.debug(
                "Add attempt failed for %s", _jid_to_string(jid), exc_info=True
            )
            self._last_error_code = 0
            return AddStatus.FAILED, f"error: {str(exc)[:160]}"

        results = list(response or ())
        if not results:
            self._last_error_code = 0
            return AddStatus.FAILED, "sin confirmacion del servidor"

        code = 0
        for participant in results:
            error = int(getattr(participant, "Error", 0) or 0)
            if error not in (0, _STATUS_OK):
                code = error
                break

        self._last_error_code = code
        if code in (0, _STATUS_OK):
            return AddStatus.ADDED, ""
        if code == _STATUS_ALREADY_MEMBER:
            return AddStatus.ALREADY_MEMBER, "ya era miembro del grupo"
        return AddStatus.FAILED, f"codigo {code}"
