"""Configura el envío por Telegram: comprueba el bot y descubre el ``TELEGRAM_CHAT_ID``.

Pasos (una sola vez):

1. En Telegram, abre @BotFather → ``/newbot`` → elige nombre y usuario → copia el token.
2. Pon el token en ``.env``: ``TELEGRAM_BOT_TOKEN=<token>`` (no se versiona; nunca lo pegues en
   un chat ni en un issue).
3. Abre la conversación con tu bot y escríbele algo (p. ej. ``/start``). Para un grupo, añade el bot
   al grupo y escribe un mensaje en él.
4. Ejecuta::

       python scripts/telegram_setup.py               # comprueba el bot y lista los chats
       python scripts/telegram_setup.py --write       # escribe TELEGRAM_CHAT_ID en .env
       python scripts/telegram_setup.py --write --chat-id 123456789   # si hay varios chats
       python scripts/telegram_setup.py --test        # envía un mensaje corto de prueba

``--write`` solo cambia (o añade) la línea ``TELEGRAM_CHAT_ID=`` de ``.env``; el resto de líneas se
conserva tal cual. ``getUpdates`` solo ve los mensajes de las últimas 24 h y no funciona si el bot
tiene un webhook configurado.

Salida: 0 si todo ha ido bien · 1 si falta el token, la API falla o no hay chat que usar.
El token **nunca** se imprime: cualquier error pasa por la redacción de ``telegram_sender``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from briefer.brand import BRAND_NAME
from briefer.config import Settings, get_settings
from briefer.delivery.telegram_sender import TelegramError, call_api

ENV_KEY = "TELEGRAM_CHAT_ID"
#: Tipos de actualización de la Bot API que traen un ``chat``.
_UPDATE_KINDS = ("message", "edited_message", "channel_post", "edited_channel_post", "my_chat_member",
                 "chat_member", "chat_join_request")


@dataclass(frozen=True)
class ChatInfo:
    """Chat que ha escrito al bot (o en el que se le ha añadido)."""

    id: str
    type: str
    name: str


def _chat_name(chat: dict[str, Any]) -> str:
    if chat.get("title"):
        return str(chat["title"])
    full = " ".join(str(chat[k]) for k in ("first_name", "last_name") if chat.get(k))
    if chat.get("username"):
        full = f"{full} (@{chat['username']})" if full else f"@{chat['username']}"
    return full or "(sin nombre)"


def parse_chats(updates: list[dict[str, Any]]) -> list[ChatInfo]:
    """Chats únicos de una lista de ``getUpdates``, en orden de aparición (el último, el más reciente)."""
    seen: dict[str, ChatInfo] = {}
    for update in updates or []:
        if not isinstance(update, dict):
            continue
        chats = [update.get(kind, {}).get("chat") for kind in _UPDATE_KINDS if isinstance(update.get(kind), dict)]
        callback = update.get("callback_query")
        if isinstance(callback, dict) and isinstance(callback.get("message"), dict):
            chats.append(callback["message"].get("chat"))
        for chat in chats:
            if isinstance(chat, dict) and chat.get("id") is not None:
                info = ChatInfo(id=str(chat["id"]), type=str(chat.get("type", "?")), name=_chat_name(chat))
                seen.pop(info.id, None)
                seen[info.id] = info
    return list(seen.values())


def write_env_value(env_path: Path, key: str, value: str) -> None:
    """Escribe ``key=value`` en ``env_path`` cambiando solo esa línea (o añadiéndola al final).

    Conserva el resto de líneas, comentarios y finales de línea. Crea el fichero si no existe.
    """
    # Bytes y no read_text: read_text convierte \r\n en \n y se perderían los finales de Windows.
    raw = env_path.read_bytes() if env_path.exists() else b""
    try:
        text = raw.decode("utf-8-sig")  # sin BOM: la clave de la 1.ª línea se reconoce
    except UnicodeDecodeError:
        text = raw.decode("cp1252")  # .env guardado en ANSI (Bloc de notas antiguo)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    new_line = f"{key}={value}"
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
        name = stripped.split("=", 1)[0].strip()
        if "=" in stripped and not stripped.startswith("#") and name == key:
            ending = line[len(line.rstrip("\r\n")):]
            if not replaced:
                lines[i] = new_line + ending
                replaced = True
            else:
                lines[i] = ""  # duplicado: se queda solo la primera aparición
    if not replaced:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        lines.append(new_line + newline)
    env_path.write_text("".join(lines), encoding="utf-8", newline="")


def _pick_chat(chats: list[ChatInfo], wanted: str | None) -> ChatInfo | None:
    if wanted:
        for chat in chats:
            if chat.id == wanted:
                return chat
        return ChatInfo(id=wanted, type="?", name="(indicado con --chat-id)")
    return chats[0] if len(chats) == 1 else None


def main(argv: list[str] | None = None, settings: Settings | None = None, env_path: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Configura el envío de {BRAND_NAME} por Telegram.")
    parser.add_argument("--write", action="store_true", help=f"escribe {ENV_KEY} en .env")
    parser.add_argument("--test", action="store_true", help="envía un mensaje corto de prueba")
    parser.add_argument("--chat-id", help="chat a usar si hay varios (o uno que no aparezca)")
    parser.add_argument("--env-file", type=Path, default=None, help="ruta del .env (por defecto, el del repo)")
    args = parser.parse_args(argv)
    # Nombres de chat con emojis: en una consola o redirección cp1252 no deben acabar en traceback.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    s = settings or get_settings()
    env_file = args.env_file or env_path or ROOT / ".env"
    secret = s.telegram_bot_token
    token = (secret.get_secret_value() if secret is not None else "").strip()
    if not token:
        print("Falta TELEGRAM_BOT_TOKEN en .env. Créalo con @BotFather (/newbot) y vuelve a ejecutar.")
        return 1

    try:
        me = call_api(token, "getMe") or {}
        print(f"Bot OK: @{me.get('username', '?')} ({me.get('first_name', '')})")
        updates = call_api(token, "getUpdates") or []
    except TelegramError as exc:  # el mensaje ya va sin token
        print(f"Error de la API de Telegram: {exc}")
        if getattr(exc, "error_code", None) == 401:
            print("El token no es válido: revisa TELEGRAM_BOT_TOKEN en .env.")
        elif getattr(exc, "error_code", None) == 409:
            print("El bot tiene un webhook activo: getUpdates no funciona mientras exista.")
        return 1

    chats = parse_chats(updates if isinstance(updates, list) else [])
    if chats:
        print(f"Chats que han escrito al bot ({len(chats)}):")
        for chat in chats:
            print(f"  {chat.id:>16}  {chat.type:<10}  {chat.name}")
    else:
        print("Nadie ha escrito todavía al bot (o hace más de 24 h): escríbele /start y repite.")

    chosen = _pick_chat(chats, args.chat_id)
    current = (s.telegram_chat_id or "").strip()
    if chosen is None and len(chats) > 1 and (args.write or args.test):
        print("Hay varios chats: elige uno con --chat-id <id>.")
        return 1

    if args.write:
        if chosen is None:
            print(f"No hay chat que escribir en {ENV_KEY}.")
            return 1
        write_env_value(env_file, ENV_KEY, chosen.id)
        print(f"{ENV_KEY}={chosen.id} escrito en {env_file.name} ({chosen.name}).")
    elif chosen is not None and chosen.id != current:
        print(f"Para usarlo: python scripts/telegram_setup.py --write"
              f"{' --chat-id ' + chosen.id if args.chat_id else ''}")

    if args.test:
        target = chosen.id if chosen is not None else current
        if not target:
            print(f"No hay chat para la prueba: falta {ENV_KEY} y nadie ha escrito al bot.")
            return 1
        try:
            call_api(token, "sendMessage", {
                "chat_id": target,
                "text": f"Prueba de {BRAND_NAME}: el bot está bien configurado. Aquí llegará el cierre del día.",
            })
        except TelegramError as exc:
            print(f"No se pudo enviar la prueba: {exc}")
            return 1
        print(f"Mensaje de prueba enviado al chat {target}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
