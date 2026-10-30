"""Build the editor launcher's Lambda package so the same source always gives the same bytes.

Entries are stored, not deflated, with a fixed date and mode: compressed bytes can differ between
zlib builds, and the package's hash names the asset and pins what Lambda may run.
"""

import base64
import hashlib
import io
import re
import zipfile
from pathlib import Path

SOURCE = Path(__file__).with_name("editor_launcher.py")
ARCHIVE_NAME = re.compile(r"editor-launcher-[0-9a-f]{16}\.zip")


def package(source: Path = SOURCE) -> bytes:
    """Return the ZIP holding only ``editor_launcher.py``."""
    entry = zipfile.ZipInfo("editor_launcher.py", date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    entry.compress_type = zipfile.ZIP_STORED
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(entry, source.read_bytes())
    return buffer.getvalue()


def archive_name(data: bytes) -> str:
    """The asset's name, which changes whenever its bytes do."""
    return f"editor-launcher-{hashlib.sha256(data).hexdigest()[:16]}.zip"


def named_for(name: str, data: bytes) -> bool:
    """Whether an asset's name matches its bytes."""
    return name == archive_name(data)


def code_sha256(data: bytes) -> str:
    """Lambda's CodeSha256 for the package: the base64 SHA-256 of its bytes."""
    return base64.b64encode(hashlib.sha256(data).digest()).decode()
