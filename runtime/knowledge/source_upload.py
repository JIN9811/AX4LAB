"""Bounded, non-overwriting intake into the Knowledge-owned source inbox."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import tempfile
import unicodedata

from knowledge.source_extraction import MAX_SOURCE_BYTES, source_format


class SourceUploadConflict(ValueError):
    pass


class SourceUploadTooLarge(ValueError):
    pass


def _finish(staging: Path, destination: Path, digest: str) -> bool:
    try:
        # Atomic no-clobber publication on the inbox filesystem.
        os.link(staging, destination)
        return False
    except FileExistsError:
        if destination.is_symlink() or not destination.is_file():
            raise SourceUploadConflict("The destination is not a regular source file")
        with destination.open("rb") as stream:
            existing = hashlib.file_digest(stream, "sha256").hexdigest()
        if existing != digest:
            raise SourceUploadConflict("A different file already has this name. Rename the new file before uploading.")
        return True


async def receive_source(library, filename: str, chunks) -> dict:
    filename = unicodedata.normalize("NFC", filename)
    if (not filename or filename != filename.strip() or filename.startswith(".")
            or len(filename.encode("utf-8")) > 240
            or any(ord(c) < 32 or c in '/\\:' for c in filename)):
        raise ValueError("Use a plain filename, without folders or hidden-file prefixes")
    source_format(Path(filename))
    digest = hashlib.sha256()
    size = 0
    fd, temporary = tempfile.mkstemp(prefix=".source-upload-", suffix=".part", dir=library.inbox)
    staging = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            async for chunk in chunks:
                size += len(chunk)
                if size > MAX_SOURCE_BYTES:
                    raise SourceUploadTooLarge("Source files must be 64 MiB or smaller")
                digest.update(chunk)
                await asyncio.to_thread(stream.write, chunk)
            if not size:
                raise ValueError("The uploaded file is empty")
            stream.flush()
            await asyncio.to_thread(os.fsync, stream.fileno())
        sha256 = digest.hexdigest()
        duplicate = await asyncio.to_thread(_finish, staging, library.inbox / filename, sha256)
        # The complete file is now immutable from this intake route. Two scans
        # admit it through the same stability/content-addressing path as folders.
        await asyncio.to_thread(library.scan)
        await asyncio.to_thread(library.scan)
        return {"status": "uploaded", "filename": filename, "size_bytes": size,
                "source_id": f"source-{sha256}", "sha256": sha256, "duplicate": duplicate}
    finally:
        staging.unlink(missing_ok=True)
