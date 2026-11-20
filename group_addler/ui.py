from __future__ import annotations

import asyncio
import csv
import logging
import time
from pathlib import Path

import flet as ft

from .limits import DEFAULT_POLICY_NAME, POLICIES, RatePolicy, UsageLimiter, get_policy
from .models import AddStatus, Group, Member
from .paths import default_session_path, exports_dir
from .service import (
    LOGIN_TIMEOUT_SECONDS,
    AddProgress,
    AddSummary,
    ConnectionState,
    WhatsAppService,
)

logger = logging.getLogger(__name__)


class GroupAddlerApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Group Addler"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window.width = 560
        self.page.window.height = 760
        self.page.window.min_width = 480
        self.page.window.min_height = 600
        self.page.on_close = self._on_page_close

        self.all_groups: list[Group] = []
        self.policy: RatePolicy = get_policy(DEFAULT_POLICY_NAME)
        self.limiter = UsageLimiter()
        self.service = WhatsAppService(
            default_session_path(),
            policy=self.policy,
            limiter=self.limiter,
        )
        self.is_running = False
        self._connecting = False
        self._summary: AddSummary | None = None
        self._cancel_event: asyncio.Event | None = None
        self._add_task: asyncio.Task[None] | None = None
        self._qr_version = 0
        self._last_message = ""

        self._setup_ui()
        self.service.start()

    # -------------------------------------------------------------------- ui

    def _setup_ui(self) -> None:
        self.qr_status_text = ft.Text(
            "Conectando con WhatsApp...",
            size=18,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
        )
        self.qr_hint_text = ft.Text(
            "Abre WhatsApp > Dispositivos vinculados > Vincular un dispositivo",
            size=12,
            text_align=ft.TextAlign.CENTER,
        )
        self.qr_image_holder = ft.Container(width=300, height=300)
        self.qr_progress = ft.ProgressRing()
        self.retry_button = ft.Button(
            content="Reintentar conexion",
            visible=False,
            on_click=self.on_retry_clicked,
        )
        self.qr_container = ft.Container(
            content=ft.Column(
                [
                    self.qr_status_text,
                    self.qr_hint_text,
                    self.qr_image_holder,
                    self.qr_progress,
                    self.retry_button,
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
            ),
            expand=True,
            alignment=ft.Alignment.CENTER,
        )

        self.source_dropdown = ft.Dropdown(
            label="Grupo de origen",
            options=[],
            on_select=self._on_selection_change,
        )
        self.target_dropdown = ft.Dropdown(
            label="Grupo destino",
            options=[],
            on_select=self._on_selection_change,
        )
        self.add_button = ft.Button(
            content="Agregar participantes",
            height=48,
            disabled=True,
            on_click=self.on_add_clicked,
        )
        self.cancel_button = ft.Button(
            content="Cancelar",
            height=44,
            visible=False,
            on_click=self.on_cancel_clicked,
        )
        self.reload_button = ft.OutlinedButton(
            content="Recargar grupos",
            on_click=self.on_reload_clicked,
        )
        self.policy_dropdown = ft.Dropdown(
            label="Ritmo de agregado",
            options=[
                ft.DropdownOption(key=policy.name, text=policy.label)
                for policy in POLICIES.values()
            ],
            value=DEFAULT_POLICY_NAME,
            on_select=self._on_policy_change,
        )
        self.limits_text = ft.Text("", size=11)
        self.export_button = ft.OutlinedButton(
            content="Exportar resultados",
            disabled=True,
            on_click=self.on_export_clicked,
        )
        self.status_text = ft.Text("", size=13)
        self.progress = ft.ProgressBar(visible=False, value=0)
        self.added_value = ft.Text("0", size=14, weight=ft.FontWeight.BOLD)
        self.skipped_value = ft.Text("0", size=14, weight=ft.FontWeight.BOLD)
        self.failed_value = ft.Text("0", size=14, weight=ft.FontWeight.BOLD)
        self.results_list = ft.ListView(expand=True, spacing=2)

        self.main_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Agregar participantes entre grupos",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        "Se agregan solo las personas que no estan en el destino.",
                        size=12,
                    ),
                    ft.Container(height=8),
                    self.source_dropdown,
                    self.target_dropdown,
                    ft.Row([self.reload_button], alignment=ft.MainAxisAlignment.END),
                    self.policy_dropdown,
                    self.limits_text,
                    ft.Container(height=4),
                    self.add_button,
                    self.cancel_button,
                    self.progress,
                    self.status_text,
                    ft.Row(
                        [
                            ft.Text("Agregados: ", size=13),
                            self.added_value,
                            ft.Text("  Ya estaban: ", size=13),
                            self.skipped_value,
                            ft.Text("  Fallidos: ", size=13),
                            self.failed_value,
                        ]
                    ),
                    ft.Container(
                        content=self.results_list,
                        height=200,
                        padding=8,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                    ),
                    ft.Row(
                        [self.export_button],
                        alignment=ft.MainAxisAlignment.END,
                    ),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            expand=True,
            padding=20,
            visible=False,
        )

        self.page.add(
            ft.Column(
                [self.qr_container, self.main_container],
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )

    # --------------------------------------------------------------- lifecycle

    async def run(self) -> None:
        await self._connection_flow()

    def _on_page_close(self, _event: ft.ControlEvent) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        try:
            self.service.stop()
        except Exception:
            logger.debug("Error while stopping service", exc_info=True)

    # -------------------------------------------------------------- connection

    async def _connection_flow(self) -> None:
        self.main_container.visible = False
        self.qr_container.visible = True
        self.retry_button.visible = False
        self.qr_progress.visible = True
        self.qr_image_holder.content = None
        self._last_message = ""
        self._set_qr_status("Conectando con WhatsApp...")
        self.page.update()

        deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS

        while True:
            snapshot = self.service.snapshot()

            if (
                snapshot.qr_data_uri
                and snapshot.qr_version != self._qr_version
            ):
                self._qr_version = snapshot.qr_version
                deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
                self.qr_image_holder.content = ft.Image(
                    src=snapshot.qr_data_uri,
                    width=300,
                    height=300,
                    fit=ft.BoxFit.CONTAIN,
                )
                self.qr_hint_text.value = (
                    "El codigo cambia cada pocos segundos: escanea el mas reciente."
                )
                self.page.update()

            if snapshot.message and snapshot.message != self._last_message:
                self._last_message = snapshot.message
                self._set_qr_status(snapshot.message)

            if snapshot.state is ConnectionState.READY:
                break
            if snapshot.state in (
                ConnectionState.FAILED,
                ConnectionState.LOGGED_OUT,
            ):
                self._show_connection_error(
                    snapshot.message or "No se pudo conectar con WhatsApp."
                )
                return
            if time.monotonic() > deadline:
                self._show_connection_error(
                    "WhatsApp no respondio a tiempo. Reintenta la conexion."
                )
                return

            await asyncio.sleep(0.5)

        self.qr_progress.visible = False
        await self._load_groups()

    def _set_qr_status(self, message: str) -> None:
        self.qr_status_text.value = message
        self.page.update()

    def _show_connection_error(self, message: str) -> None:
        self.qr_progress.visible = False
        self.qr_hint_text.value = ""
        self.retry_button.visible = True
        self._set_qr_status(message)

    def on_retry_clicked(self, _event: ft.ControlEvent) -> None:
        asyncio.create_task(self._retry_connection())

    async def _retry_connection(self) -> None:
        if self._connecting:
            return
        self._connecting = True
        try:
            await asyncio.to_thread(self.service.stop)
            self.service = WhatsAppService(
                default_session_path(),
                policy=self.policy,
                limiter=self.limiter,
            )
            self.service.start()
            self._qr_version = 0
            await self._connection_flow()
        finally:
            self._connecting = False

    # ------------------------------------------------------------------ groups

    async def _load_groups(self) -> None:
        self._set_main_status("Cargando grupos...")
        try:
            groups = await asyncio.to_thread(self.service.get_groups)
        except Exception:
            logger.exception("Failed to load groups")
            self._show_main_panel([])
            self._set_main_status(
                "No se pudieron cargar los grupos. Usa 'Recargar grupos'."
            )
            return
        self._show_main_panel(groups)

    def _show_main_panel(self, groups: list[Group]) -> None:
        self.all_groups = groups
        options = [
            ft.DropdownOption(
                key=group.id,
                text=(
                    f"{group.name} ({group.member_count} miembros)"
                    f"{' - admin' if group.is_admin else ''}"
                ),
            )
            for group in groups
        ]
        self.source_dropdown.options = options
        self.target_dropdown.options = options
        self.source_dropdown.value = None
        self.target_dropdown.value = None
        self._update_add_button()
        self._update_limits_text()

        admin_count = sum(1 for group in groups if group.is_admin)
        self._set_main_status(
            f"{len(groups)} grupos disponibles ({admin_count} como admin). "
            "Elegi origen y destino."
        )
        self.qr_container.visible = False
        self.main_container.visible = True
        self.page.update()

    def on_reload_clicked(self, _event: ft.ControlEvent) -> None:
        asyncio.create_task(self._reload_groups())

    async def _reload_groups(self) -> None:
        if self.is_running:
            return
        self.reload_button.disabled = True
        self.page.update()
        try:
            await self._load_groups()
        finally:
            self.reload_button.disabled = False
            self.page.update()

    def _on_selection_change(self, _event: ft.ControlEvent) -> None:
        self._update_add_button()
        self.page.update()

    def _update_add_button(self) -> None:
        source = self.source_dropdown.value
        target = self.target_dropdown.value
        self.add_button.disabled = (
            self.is_running
            or not source
            or not target
            or source == target
        )

    def _on_policy_change(self, _event: ft.ControlEvent) -> None:
        self.policy = get_policy(self.policy_dropdown.value)
        self.service.set_policy(self.policy)
        self._update_limits_text()
        self.page.update()

    def _update_limits_text(self) -> None:
        hour_left = self.limiter.remaining_this_hour(self.policy)
        day_left = self.limiter.remaining_today(self.policy)
        self.limits_text.value = (
            f"Margen de la cuenta: {hour_left} agregados esta hora, "
            f"{day_left} hoy."
        )

    def _estimate_duration(self, count: int) -> str:
        policy = self.policy
        average = (policy.min_delay + policy.max_delay) / 2
        pause = (policy.batch_pause_min + policy.batch_pause_max) / 2
        seconds = 0.0
        for index in range(1, count):
            seconds += pause if index % policy.batch_size == 0 else average
        minutes = seconds / 60
        if minutes < 1:
            return "menos de 1 minuto"
        return f"~{minutes:.0f} minutos"

    def _on_wait(self, seconds: int) -> None:
        self._set_main_status(f"Esperando {seconds}s antes del proximo agregado...")

    # -------------------------------------------------------------------- add

    def on_add_clicked(self, _event: ft.ControlEvent) -> None:
        if self.is_running:
            return
        self._add_task = asyncio.create_task(self._prepare_and_add())

    async def _prepare_and_add(self) -> None:
        if self.is_running:
            return

        source = self._find_group(self.source_dropdown.value)
        target = self._find_group(self.target_dropdown.value)

        if source is None or target is None:
            self._set_main_status("Selecciona ambos grupos.")
            return
        if source.id == target.id:
            self._set_main_status("Selecciona grupos diferentes.")
            return

        blocked = self.limiter.blocked_reason(self.policy)
        if blocked:
            self._set_main_status(blocked)
            return

        self.service.set_policy(self.policy)
        self.is_running = True
        self._begin_run()

        try:
            self._set_main_status("Calculando destinatarios...")
            plan = await self.service.plan_add(source, target)

            if not plan:
                self._set_main_status("No hay participantes nuevos para agregar.")
                return

            self._set_main_status(
                f"Se agregaran {len(plan)} personas a \"{target.name}\"."
            )
            self.page.update()

            if not await self._confirm_add(plan, target):
                self._set_main_status("Operacion cancelada.")
                return

            self._cancel_event = asyncio.Event()
            self.cancel_button.visible = True
            self.progress.value = 0
            self._set_main_status(f"Agregando 0/{len(plan)}...")
            self.page.update()

            summary = await self.service.add_participants(
                target,
                plan,
                on_progress=self._on_progress,
                cancel=self._cancel_event,
                on_wait=self._on_wait,
            )
            self._summary = summary
            self.added_value.value = str(summary.added)
            self.skipped_value.value = str(summary.skipped)
            self.failed_value.value = str(summary.failed)
            self._render_results(summary)
            totals = (
                f"Agregados: {summary.added}, "
                f"ya estaban: {summary.skipped}, "
                f"fallidos: {summary.failed}."
            )
            if summary.abort_reason:
                self._set_main_status(f"Detenido: {summary.abort_reason} {totals}")
            elif summary.cancelled:
                self._set_main_status(f"Cancelado. {totals}")
            else:
                self._set_main_status(f"Completado. {totals}")
        except Exception as exc:
            logger.exception("Failed to add participants")
            self._set_main_status(f"Error: {exc}")
        finally:
            self._finish_run()

    def _begin_run(self) -> None:
        self._set_controls_enabled(False)
        self.cancel_button.visible = False
        self.export_button.disabled = True
        self.progress.visible = True
        self.progress.value = None
        self._summary = None
        self._cancel_event = None
        self.added_value.value = "0"
        self.skipped_value.value = "0"
        self.failed_value.value = "0"
        self.results_list.controls = []
        self.page.update()

    def _finish_run(self) -> None:
        self.is_running = False
        self._cancel_event = None
        self.cancel_button.visible = False
        self.progress.visible = False
        self.progress.value = 0
        self._set_controls_enabled(True)
        self._update_limits_text()
        self._update_add_button()
        self.page.update()

    def _on_progress(self, progress: AddProgress) -> None:
        self.added_value.value = str(progress.added)
        self.skipped_value.value = str(progress.skipped)
        self.failed_value.value = str(progress.failed)
        if progress.total:
            self.progress.value = progress.processed / progress.total
        self._set_main_status(
            f"Agregando {progress.processed}/{progress.total}..."
        )

    def on_cancel_clicked(self, _event: ft.ControlEvent) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._set_main_status("Cancelando...")

    async def _confirm_add(self, plan: list[Member], target: Group) -> bool:
        future: asyncio.Future[bool] = (
            asyncio.get_running_loop().create_future()
        )

        def close(confirmed: bool) -> None:
            if not future.done():
                future.set_result(confirmed)

        def on_action(confirmed: bool):
            def handler(_event: ft.ControlEvent) -> None:
                self.page.pop_dialog()
                close(confirmed)

            return handler

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirmar agregado"),
            content=ft.Text(
                f"Se agregaran {len(plan)} personas al grupo \"{target.name}\".\n\n"
                f"Ritmo \"{self.policy.label}\": duracion estimada "
                f"{self._estimate_duration(len(plan))}.\n\n"
                "Esta accion no se puede deshacer y agregar personas en masa "
                "puede infringir las politicas de WhatsApp."
            ),
            actions=[
                ft.TextButton(
                    content="Cancelar",
                    on_click=on_action(False),
                ),
                ft.TextButton(
                    content="Agregar",
                    on_click=on_action(True),
                ),
            ],
            on_dismiss=lambda _event: close(False),
        )

        self.page.show_dialog(dialog)
        return await future

    # --------------------------------------------------------------- results

    def _render_results(self, summary: AddSummary) -> None:
        controls: list[ft.Control] = []
        for result in summary.results:
            if result.status is AddStatus.ADDED:
                mark, color = "OK", ft.Colors.GREEN
            elif result.status is AddStatus.ALREADY_MEMBER:
                mark, color = "YA", ft.Colors.AMBER
            else:
                mark, color = "FALLO", ft.Colors.RED

            identifier = result.member.pn or result.member.lid or result.member.user_id
            text = f"{mark}  {result.member.label} ({identifier})"
            if result.detail:
                text = f"{text} - {result.detail}"
            controls.append(ft.Text(text, size=12, color=color))

        self.results_list.controls = controls
        self.export_button.disabled = not summary.results

    def on_export_clicked(self, _event: ft.ControlEvent) -> None:
        summary = self._summary
        if summary is None:
            return
        try:
            path = self._write_csv(summary)
        except OSError as exc:
            logger.exception("Failed to export results")
            self._set_main_status(f"No se pudo exportar: {exc}")
            return
        self._set_main_status(f"Resultados exportados a {path}")

    @staticmethod
    def _write_csv(summary: AddSummary) -> Path:
        path = exports_dir() / time.strftime("resultados-%Y%m%d-%H%M%S.csv")
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(summary.export_rows())
        return path

    # ----------------------------------------------------------------- helpers

    def _set_main_status(self, message: str) -> None:
        self.status_text.value = message
        self.page.update()

    def _find_group(self, group_id: str | None) -> Group | None:
        if group_id is None:
            return None
        return next(
            (group for group in self.all_groups if group.id == group_id),
            None,
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.add_button.disabled = not enabled
        self.source_dropdown.disabled = not enabled
        self.target_dropdown.disabled = not enabled
        self.reload_button.disabled = not enabled
        self.policy_dropdown.disabled = not enabled


async def main(page: ft.Page) -> None:
    app = GroupAddlerApp(page)
    await app.run()
