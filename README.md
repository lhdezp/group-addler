# Group Addler

Aplicación de escritorio (Flet + Neonize) para copiar participantes de un grupo
de WhatsApp a otro. Inicia sesión escaneando un código QR, lista los grupos del
usuario y agrega a quienes todavía no están en el grupo destino.

## Requisitos

- Python 3.14 o superior
- Una cuenta de WhatsApp
- Conexión a internet

## Instalación

```bash
uv sync
```

Si vas a ejecutar las pruebas o empaquetar el `.exe`, instalá también las
dependencias de desarrollo:

```bash
uv sync --group dev
```

Si no usás `uv`, instalá las dependencias con `pip install -e .`.

## Ejecución

```bash
uv run python main.py
```

Al iniciar, la aplicación muestra un código QR. Escanealo desde
WhatsApp > Dispositivos vinculados. La sesión se guarda para no tener que
escanear el QR en cada arranque. Si el QR vence o la conexión falla, aparece el
botón **Reintentar conexión**.

Los datos de la aplicación viven fuera del repositorio, en
`%APPDATA%\GroupAddler\`:

| Ruta | Contenido |
| --- | --- |
| `whatsapp_session` | Credenciales de la sesión de WhatsApp |
| `logs\group-addler.log` | Log rotativo de ejecución |
| `exports\resultados-*.csv` | Resultados exportados |
| `rate-limit.json` | Agregados recientes para los topes por hora y por día |

Al arrancar, si existe un `whatsapp_session` junto al código o al `.exe`, se
mueve automáticamente al nuevo directorio.

## Uso

1. Elegí el **grupo de origen** (de dónde se copian los miembros).
2. Elegí el **grupo destino** (se muestran todos los grupos; los que tenés como
   administrador aparecen marcados con `- admin`).
3. Elegí el **ritmo de agregado**:
   - **Cauto** (recomendado): 12-22 s entre agregados, pausa de 40-60 s cada 5,
     hasta 25 por hora y 60 por día.
   - **Normal**: 7-13 s entre agregados, pausa de 25-40 s cada 6, hasta 45 por
     hora y 120 por día.
   - **Rápido**: 3-6 s entre agregados, pausa de 12-20 s cada 5, hasta 80 por
     hora y 240 por día. Mayor riesgo de restricción.

   Los valores son aleatorios dentro de cada rango para no repetir un patrón
   fijo. Los topes se guardan en disco, así que reiniciar la aplicación no los
   reinicia.
4. Presioná **Agregar participantes**.
5. Revisá la cantidad de personas a agregar, la duración estimada y confirmá en
   el diálogo.

Durante la operación podés **Cancelar**: se detiene después del agregado en
curso. Al terminar se muestra el detalle por persona (agregado, ya era miembro
o fallido con su motivo) y podés **Exportar resultados** a CSV.

La operación se detiene sola cuando WhatsApp reporta un límite (por ejemplo
código 429), cuando la cuenta recibe una restricción temporal o cuando hay tres
fallos consecutivos. En esos casos no se siguen enviando solicitudes.

La aplicación omite a los miembros que ya están en el destino y al usuario
actual, comparando por número de teléfono y por LID. Cuando un participante solo
se conoce por LID, se resuelve su teléfono antes de agregarlo y, si el intento
por LID falla, se reintenta con el número. Se aplican pausas aleatorias, topes
por hora/día y un descanso entre tandas para reducir el riesgo de bloqueos.

## Seguridad

- `whatsapp_session` contiene credenciales de la cuenta: **nunca** debe subirse
  al repositorio. Ya está incluido en `.gitignore`.
- El código QR y la sesión son equivalentes a la contraseña de la cuenta. Tratá
  esos archivos como secretos.
- El QR se muestra embebido en la interfaz; no se escriben archivos temporales.

## Riesgos de uso

Agregar miembros de forma masiva puede infringir las políticas de WhatsApp y
provocar restricciones o bloqueos de la cuenta. Usá la herramienta con grupos
propios y de forma moderada.

## Estructura

```
main.py                     Punto de entrada (Flet, logging y migración de sesión)
group_addler/models.py      Modelos y selección de miembros (lógica pura)
group_addler/paths.py       Rutas de datos de usuario y migración de sesión
group_addler/limits.py      Ritmos, topes por hora/día y descanso entre tandas
group_addler/service.py     Integración con WhatsApp (Neonize) y rate limiting
group_addler/ui.py          Interfaz Flet
tests/                      Pruebas unitarias
build.py                    Empaquetado con PyInstaller
```

## Pruebas

```bash
uv run python -m unittest discover -s tests -v
```

## Empaquetado (Windows)

```bash
uv run python build.py
```

El ejecutable se genera en `dist/GroupAddler/`. Copiá la carpeta completa a la
máquina destino: el ejecutable necesita los archivos que la acompañan.
