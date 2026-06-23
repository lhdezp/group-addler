import flet as ft
import asyncio
from WPP_Whatsapp import Create


class WhatsAppGroupApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "WhatsApp Group Admin"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window.width = 500
        self.page.window.height = 650
        
        self.client = None
        self.all_groups = []
        self.admin_groups = []
        self.total_added = 0
        self.failed = 0
        self.is_running = False
        self.login_done = False
        
        self.setup_ui()
        self.load_whatsapp()
    
    def setup_ui(self):
        self.qr_container = ft.Container(
            content=ft.Column([
                ft.Text("Iniciando WhatsApp...", size=20, weight=ft.FontWeight.BOLD),
                ft.Text("Escanea el QR en la ventana del navegador", size=14),
                ft.ProgressRing(),
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            expand=True,
        )
        
        self.source_group_dropdown = ft.Dropdown(label="Grupo de origen", width=450)
        self.target_group_dropdown = ft.Dropdown(label="Grupo destino (puedes agregar)", width=450)
        self.add_button = ft.Button("Agregar Participantes", width=450, height=50, on_click=self.on_add_clicked)
        self.status_text = ft.Text("", size=16)
        self.progress = ft.ProgressBar(width=450, visible=False)
        self.added_count = ft.Text("0", size=14, weight=ft.FontWeight.BOLD)
        self.failed_count = ft.Text("0", size=14, weight=ft.FontWeight.BOLD)
        
        self.main_container = ft.Container(
            content=ft.Column([
                ft.Text("Agregar Participantes de Grupo", size=20, weight=ft.FontWeight.BOLD),
                ft.Text("Selecciona el grupo de origen y el grupo destino", size=14),
                ft.Container(height=20),
                ft.Text("Grupos donde estas:", weight=ft.FontWeight.BOLD),
                self.source_group_dropdown,
                ft.Container(height=10),
        ft.Text("Grupo destino (donde puedes agregar):", weight=ft.FontWeight.BOLD),
        self.target_group_dropdown,
                ft.Container(height=20),
                self.add_button,
                ft.Container(height=20),
                self.status_text,
                self.progress,
                ft.Container(height=10),
                ft.Row([
                    ft.Text("Agregados: ", size=14),
                    self.added_count,
                    ft.Text("  |  Fallidos: ", size=14),
                    self.failed_count,
                ]),
            ], scroll=ft.ScrollMode.AUTO),
            padding=20,
            visible=False,
        )
        
        self.page.add(ft.Column([self.qr_container, self.main_container]))
    
    def load_whatsapp(self):
        def run():
            try:
                creator = Create(session="whatsapp_groups", headless=False, browser="chromium", channel="msedge")
                self.client = creator.start()
                self.client.waitForLogin()
                self.login_done = True
            except Exception as e:
                print(f"Error: {e}")
                self.login_done = True
        
        import threading
        threading.Thread(target=run, daemon=True).start()
    
    async def check_login_and_load(self):
        while self.client is None:
            await asyncio.sleep(0.5)
        while not self.login_done:
            await asyncio.sleep(0.5)
        await asyncio.sleep(2)
        self.load_groups()
        self.show_main_interface()
    
    def can_add_members(self, group_metadata, is_admin):
        """Verifica si el usuario puede agregar miembros al grupo.
        Puede agregar si:
        1. Es admin del grupo, OR
        2. El grupo no está restringido (cualquiera puede invitar)
        """
        # Si es admin, siempre puede agregar
        if is_admin:
            return True
        
        # Verificar si el grupo está restringido
        # restrict = true significa solo admins pueden agregar
        restrict = group_metadata.get("restrict", False)
        if restrict:
            return False
        
        # Si no está restringido, cualquiera puede agregar
        return True

    def load_groups(self):
        print("=== Cargando grupos ===")

        my_id = ""
        my_id_lid = ""
        
        # Intentar obtener mi ID del lastReceivedKey.participant
        try:
            all_chats = self.client.listChats({"onlyGroups": True})
            if all_chats:
                for chat in all_chats:
                    # Intentar obtener desde lastReceivedKey.participant
                    last_key = chat.get("lastReceivedKey", {})
                    if last_key:
                        participant = last_key.get("participant", {})
                        if isinstance(participant, dict):
                            user_num = participant.get("user", "")
                            if user_num:
                                my_id = f"{user_num}@c.us"
                                my_id_lid = f"{user_num}@lid"
                                print(f"Mi ID (desde lastReceivedKey): {my_id}, LID: {my_id_lid}")
                                break
                        
            if not my_id:
                print("No se pudo obtener mi ID")
        except Exception as e:
            print(f"Error obteniendo mi ID: {e}")
        
        if not "my_id_lid" in locals():
            my_id_lid = ""
        
        # Recargar para procesar
        return_early = False

        all_chats = self.client.listChats({"onlyGroups": True})
        print(f"Total grupos: {len(all_chats)}")

        if all_chats:
            print(f"Estructura primer chat: {all_chats[0]}")
            print(f"Keys primer chat: {list(all_chats[0].keys())}")

        self.all_groups = []
        self.admin_groups = []

        for i, chat in enumerate(all_chats):
            remote = chat.get("id", "")

            if isinstance(remote, dict):
                remote = remote.get("remote", "") or remote.get("_serialized", "")

            if not remote or not isinstance(remote, str) or "@g.us" not in remote:
                continue

            group_meta = chat.get("groupMetadata", {})
            name = group_meta.get("subject") or chat.get("name") or "Sin nombre"

            try:
                admins = self.client.getGroupAdmins(remote)
                # Comparar con @c.us y @lid
                is_admin = False
                if my_id or my_id_lid:
                    for admin in admins:
                        admin_id = admin if isinstance(admin, str) else admin.get("_serialized", "")
                        if my_id and admin_id == my_id:
                            is_admin = True
                            break
                        if my_id_lid and admin_id == my_id_lid:
                            is_admin = True
                            break
                
                print(f"  my_id={my_id}, my_id_lid={my_id_lid}, admins={admins}, is_admin={is_admin}")
                member_count = group_meta.get("size", 0)
                if not member_count:
                    members = self.client.getGroupMembers(remote)
                    member_count = len(members)
                
                can_add = self.can_add_members(group_meta, is_admin)
                print(f"Grupo {i}: {name[:30]} id={remote} admin={is_admin} can_add={can_add} miembros={member_count}")
            except Exception as e:
                print(f"  -> Error: {e}")
                is_admin = False
                can_add = False
                member_count = 0

            group_data = {"name": name, "id": remote, "member_count": member_count, "is_admin": is_admin, "can_add_members": can_add}
            self.all_groups.append(group_data)

            if can_add:
                self.admin_groups.append(group_data)

        print(f"Total grupos: {len(self.all_groups)}, Donde puedo agregar: {len(self.admin_groups)}")
    
    def show_main_interface(self):
        # Source dropdown: ALL groups the user is in
        self.source_group_dropdown.options = [
            ft.dropdown.Option(key=g["id"], text=f"{g['name']} ({g['member_count']} miembros)")
            for g in self.all_groups
        ]
        # Target dropdown: ONLY groups where user can add members (admin OR open group)
        self.target_group_dropdown.options = [
            ft.dropdown.Option(key=g["id"], text=f"{g['name']} ({g['member_count']} miembros) {'✓ admin' if g['is_admin'] else ''}")
            for g in self.all_groups if g["can_add_members"]
        ]
        
        if self.source_group_dropdown.options:
            self.source_group_dropdown.value = self.source_group_dropdown.options[0].key
        if self.target_group_dropdown.options:
            self.target_group_dropdown.value = self.target_group_dropdown.options[0].key
        
        can_add_count = sum(1 for g in self.all_groups if g["can_add_members"])
        self.status_text.value = f"{len(self.all_groups)} grupos, {can_add_count} donde puedes agregar"
        self.qr_container.visible = False
        self.main_container.visible = True
        self.page.update()
    
    def get_member_id(self, member):
        """Extrae el ID del miembro preservando el formato original (@lid o @c.us)."""
        if not isinstance(member, dict):
            return ""
        
        # Intenta obtener directamente el ID
        mid = member.get("id", "")
        
        # Si es un diccionario, busca remote o _serialized
        if isinstance(mid, dict):
            mid = mid.get("remote", "") or mid.get("_serialized", "")
        
        # Si ya tiene formato válido, preservarlo tal cual
        if isinstance(mid, str) and ("@c.us" in mid or "@lid" in mid):
            return mid
        
        # Si no, busca en todos los valores del diccionario
        for key, val in member.items():
            if isinstance(val, str):
                if "@c.us" in val or "@lid" in val:
                    return val
            
            # Si el valor es dict, busca dentro
            if isinstance(val, dict):
                for k2, v2 in val.items():
                    if isinstance(v2, str) and ("@c.us" in v2 or "@lid" in v2):
                        return v2
        
        return ""
    
    @staticmethod
    def get_user_number(member_id):
        """Extrae solo el número de usuario de un ID (antes del @)."""
        if not member_id:
            return ""
        return member_id.split("@")[0]
    
    def on_add_clicked(self, e):
        """Handler síncrono que inicia la tarea async."""
        asyncio.create_task(self.start_add_participants(e))
    
    async def start_add_participants(self, e):
        if self.is_running:
            return
        
        source_id = self.source_group_dropdown.value
        target_id = self.target_group_dropdown.value
        
        if not source_id or not target_id:
            self.status_text.value = "Selecciona ambos grupos"
            self.page.update()
            return
        
        if source_id == target_id:
            self.status_text.value = "Selecciona grupos diferentes"
            self.page.update()
            return
        
        # Check if user is admin in target group
        target_group = next((g for g in self.all_groups if g["id"] == target_id), None)
        if target_group and not target_group["is_admin"]:
            self.status_text.value = "⚠ No eres admin en el grupo destino - no podrás agregar miembros"
            self.page.update()
            # Continue anyway but warn user
        
        self.is_running = True
        self.add_button.disabled = True
        self.progress.visible = True
        self.total_added = 0
        self.failed = 0
        self.added_count.value = "0"
        self.failed_count.value = "0"
        self.status_text.value = "Obteniendo miembros..."
        self.page.update()
        
        try:
            print(f"Obteniendo miembros de source: {source_id}")
            source_members = self.client.getGroupMembers(source_id)
            print(f"Miembros source: {len(source_members)}")
            if source_members:
                print(f"Primer miembro source completo: {source_members[0]}")
                print(f"Keys del primer miembro: {list(source_members[0].keys())}")
            
            print(f"Obteniendo miembros de target: {target_id}")
            target_members = self.client.getGroupMembers(target_id)
            print(f"Miembros target: {len(target_members)}")
            if target_members:
                print(f"Primer miembro target completo: {target_members[0]}")
                print(f"Keys del primer miembro: {list(target_members[0].keys())}")
            
            # Get IDs from target group members
            target_ids = set()
            target_numbers = set()
            for i, m in enumerate(target_members):
                mid = self.get_member_id(m)
                print(f"Target miembro {i}: ID extraído = {mid}")
                if mid:
                    target_ids.add(mid)
                    target_numbers.add(self.get_user_number(mid))
            print(f"IDs en target ({len(target_ids)}): {target_ids}")
            
            # Filter source members who are not in target
            to_add = []
            source_ids_found = []
            for i, m in enumerate(source_members):
                mid = self.get_member_id(m)
                print(f"Source miembro {i}: ID extraído = {mid}")
                if mid:
                    source_ids_found.append(mid)
                    user_num = self.get_user_number(mid)
                    # Comparar por número de usuario (ignorando formato @lid/@c.us)
                    if user_num not in target_numbers:
                        to_add.append(mid)
                        print(f"  → Este miembro SERÁ AGREGADO")
                    else:
                        print(f"  → Ya está en target, se ignora")
            
            print(f"IDs en source ({len(source_ids_found)}): {source_ids_found}")
            total = len(to_add)
            print(f"Participantes a agregar: {total}")
            
            if total == 0:
                self.status_text.value = "No hay participantes nuevos"
                self.page.update()
                return
            
            self.status_text.value = f"Agregando {total} participantes..."
            self.page.update()
            
            # Debug: obtener info del grupo destino
            try:
                target_group = None
                for g in self.all_groups:
                    if g["id"] == target_id:
                        target_group = g
                        break
                if target_group:
                    print(f"Grupo destino info: {target_group}")
            except Exception as e:
                print(f"Error obteniendo info del grupo destino: {e}")
            
            # Esperar y recargar el grupo (podría no estar sincronizado)
            print("Esperando 5 segundos antes de agregar participantes...")
            await asyncio.sleep(5)
            
            print("Intentando recargar info del grupo destino...")
            try:
                # Recargar members para asegurar sincronización
                self.client.getGroupMembers(target_id)
                print("Grupo recargado")
            except Exception as e:
                print(f"Advertencia al recargar grupo: {e}")
            
            for i, mid in enumerate(to_add):
                try:
                    resolved_id = mid
                    if mid.endswith("@lid"):
                        print(f"  Resolviendo LID {mid} a teléfono...")
                        try:
                            entry = await self.client.ThreadsafeBrowser.page_evaluate(
                                "(lid) => WPP.contact.getPnLidEntry(lid)",
                                mid, page=self.client.page
                            )
                            print(f"  Entry de getPnLidEntry: {entry}")
                            if entry and isinstance(entry, dict):
                                phone = entry.get("phoneNumber", {})
                                if isinstance(phone, dict):
                                    resolved_id = phone.get("_serialized", "")
                                elif isinstance(phone, str):
                                    resolved_id = phone
                            if not resolved_id or not resolved_id.endswith("@c.us"):
                                resolved_id = mid
                                print(f"  No se pudo resolver a teléfono, usando LID directo: {resolved_id}")
                        except Exception as resolve_ex:
                            print(f"  Error resolviendo LID: {resolve_ex}")
                            resolved_id = mid
                            print(f"  Usando LID directo: {resolved_id}")
                    
                    print(f"Agregando {resolved_id} (original: {mid}) a {target_id}")
                    
                    add_ok = False
                    errors_tried = []
                    
                    raw_phone = resolved_id.replace("@c.us", "") if resolved_id.endswith("@c.us") else ""
                    
                    # Intento 1: addParticipants con @c.us (teléfono resuelto)
                    if resolved_id.endswith("@c.us"):
                        try:
                            result = await self.client.ThreadsafeBrowser.page_evaluate(
                                """async ({ groupId, participantId }) => {
                                    try {
                                        return { ok: true, result: await WPP.group.addParticipants(groupId, participantId) };
                                    } catch(e) {
                                        return { ok: false, error: e.message || String(e) };
                                    }
                                }""",
                                {"groupId": target_id, "participantId": resolved_id},
                                page=self.client.page
                            )
                            print(f"  Resultado addParticipants(@c.us): {result}")
                            if isinstance(result, dict) and result.get("ok"):
                                add_ok = True
                                self.total_added += 1
                                self.added_count.value = str(self.total_added)
                                print(f"  ✓ Agregado exitosamente")
                            else:
                                errors_tried.append(f"addParticipants({resolved_id}): {result}")
                        except Exception as ex1:
                            err_str = str(ex1)
                            errors_tried.append(f"addParticipants({resolved_id}): {err_str}")
                            print(f"  Intento 1 falló: {err_str}")
                    
                    # Intento 2: addParticipants con @lid directo
                    if not add_ok and mid.endswith("@lid") and mid != resolved_id:
                        try:
                            print(f"  Intentando con LID directo: {mid}")
                            result = await self.client.ThreadsafeBrowser.page_evaluate(
                                """async ({ groupId, participantId }) => {
                                    try {
                                        return { ok: true, result: await WPP.group.addParticipants(groupId, participantId) };
                                    } catch(e) {
                                        return { ok: false, error: e.message || String(e) };
                                    }
                                }""",
                                {"groupId": target_id, "participantId": mid},
                                page=self.client.page
                            )
                            print(f"  Resultado addParticipants(@lid): {result}")
                            if isinstance(result, dict) and result.get("ok"):
                                add_ok = True
                                self.total_added += 1
                                self.added_count.value = str(self.total_added)
                                print(f"  ✓ Agregado con LID directo")
                            else:
                                errors_tried.append(f"addParticipants({mid}): {result}")
                        except Exception as ex2:
                            err_str = str(ex2)
                            errors_tried.append(f"addParticipants({mid}): {err_str}")
                            print(f"  Intento 2 falló: {err_str}")
                    
                    # Intento 3: addParticipants con número sin @c.us
                    if not add_ok and raw_phone:
                        try:
                            print(f"  Intentando con número sin @c.us: {raw_phone}")
                            result = await self.client.ThreadsafeBrowser.page_evaluate(
                                """async ({ groupId, participantId }) => {
                                    try {
                                        return { ok: true, result: await WPP.group.addParticipants(groupId, participantId) };
                                    } catch(e) {
                                        return { ok: false, error: e.message || String(e) };
                                    }
                                }""",
                                {"groupId": target_id, "participantId": raw_phone},
                                page=self.client.page
                            )
                            print(f"  Resultado addParticipants(raw phone): {result}")
                            if isinstance(result, dict) and result.get("ok"):
                                add_ok = True
                                self.total_added += 1
                                self.added_count.value = str(self.total_added)
                                print(f"  ✓ Agregado con número sin @c.us")
                            else:
                                errors_tried.append(f"addParticipants({raw_phone}): {result}")
                        except Exception as ex3:
                            err_str = str(ex3)
                            errors_tried.append(f"addParticipants({raw_phone}): {err_str}")
                            print(f"  Intento 3 falló: {err_str}")
                    
                    # Intento 4: addParticipants con @lid (si resolved_id no era @lid ya)
                    if not add_ok and mid.endswith("@lid"):
                        try:
                            print(f"  Intentando addParticipants con LID: {mid}")
                            result = await self.client.ThreadsafeBrowser.page_evaluate(
                                """async ({ groupId, participantId }) => {
                                    try {
                                        return { ok: true, result: await WPP.group.addParticipants(groupId, participantId) };
                                    } catch(e) {
                                        return { ok: false, error: e.message || String(e) };
                                    }
                                }""",
                                {"groupId": target_id, "participantId": mid},
                                page=self.client.page
                            )
                            print(f"  Resultado addParticipants(LID final): {result}")
                            if isinstance(result, dict) and result.get("ok"):
                                add_ok = True
                                self.total_added += 1
                                self.added_count.value = str(self.total_added)
                                print(f"  ✓ Agregado con LID (intento final)")
                            else:
                                errors_tried.append(f"addParticipants(LID:{mid}): {result}")
                        except Exception as ex4:
                            err_str = str(ex4)
                            errors_tried.append(f"addParticipants(LID:{mid}): {err_str}")
                            print(f"  Intento 4 falló: {err_str}")
                    
                    if not add_ok:
                        print(f"  ✗ Todos los intentos fallaron para {mid}:")
                        for e in errors_tried:
                            print(f"    - {e}")
                        raise Exception(f"Todos los intentos fallaron: {'; '.join(errors_tried)}")
                except Exception as ex:
                    print(f"Error agregando {mid}: {ex}")
                    print(f"Error type: {type(ex).__name__}")
                    print(f"Error str: {str(ex)}")
                    import traceback
                    traceback.print_exc()
                    self.failed += 1
                    self.failed_count.value = str(self.failed)
                
                if (i + 1) % 5 == 0:
                    self.status_text.value = f"Procesados {i+1}/{total} - Esperando..."
                    self.page.update()
                    await asyncio.sleep(15)
                else:
                    await asyncio.sleep(3)
            
            self.status_text.value = f"Completado! Agregados: {self.total_added}, Fallidos: {self.failed}"
        except Exception as e:
            self.status_text.value = f"Error: {str(e)}"
            import traceback
            traceback.print_exc()
        finally:
            self.is_running = False
            self.add_button.disabled = False
            self.progress.visible = False
            self.page.update()


async def main(page: ft.Page):
    app = WhatsAppGroupApp(page)
    await app.check_login_and_load()


if __name__ == "__main__":
    import sys
    if sys.platform == "win32" and sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    ft.app(target=main)