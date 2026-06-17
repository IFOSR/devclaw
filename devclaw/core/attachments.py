from __future__ import annotations

import base64
import mimetypes
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@dataclass(frozen=True)
class Attachment:
    path: str
    media_type: str
    note: str = ""
    source: str = "file"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def attach_image_file(project_root: Path, source: Path, note: str = "") -> Attachment:
    source_path = source.expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"image file not found: {source}")
    media_type = _image_media_type(source_path)
    destination = _pending_dir(project_root) / _unique_name(source_path.suffix.lower() or ".png")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return Attachment(
        path=str(destination.relative_to(project_root)),
        media_type=media_type,
        note=note,
        source="file",
    )


def paste_clipboard_image(project_root: Path, note: str = "") -> Attachment:
    destination = _pending_dir(project_root) / _unique_name(".png")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = _read_macos_clipboard_png()
    if not image_bytes:
        raise ValueError("clipboard does not contain an image")
    destination.write_bytes(image_bytes)
    return Attachment(
        path=str(destination.relative_to(project_root)),
        media_type="image/png",
        note=note,
        source="clipboard",
    )


def format_attachments_for_prompt(attachments: list[Attachment]) -> str:
    if not attachments:
        return ""
    lines = ["Attached screenshots:"]
    for attachment in attachments:
        lines.append(f"- {attachment.path}")
        lines.append(f"  Type: {attachment.media_type}")
        if attachment.note:
            lines.append(f"  Note: {attachment.note}")
        lines.append(f"  Source: {attachment.source}")
    return "\n".join(lines)


def append_attachments_to_intent(intent: str, attachments: list[Attachment]) -> str:
    context = format_attachments_for_prompt(attachments)
    if not context:
        return intent
    return f"{intent.rstrip()}\n\n{context}"


def _image_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_IMAGE_TYPES:
        return SUPPORTED_IMAGE_TYPES[suffix]
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed and guessed.startswith("image/"):
        return guessed
    raise ValueError(f"unsupported image file type: {path}")


def _pending_dir(project_root: Path) -> Path:
    return project_root / ".devclaw" / "attachments" / "pending"


def _unique_name(suffix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"clipboard-{timestamp}{suffix}"


def _read_macos_clipboard_png() -> bytes:
    script = r'''
ObjC.import('AppKit')
ObjC.import('Foundation')
const pasteboard = $.NSPasteboard.generalPasteboard
const data = pasteboard.dataForType('public.png') || pasteboard.dataForType('public.tiff')
if (!data) {
  $.exit(2)
}
const base64 = data.base64EncodedStringWithOptions(0)
console.log(ObjC.unwrap(base64))
'''
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return b""
    return base64.b64decode(result.stdout.strip())
