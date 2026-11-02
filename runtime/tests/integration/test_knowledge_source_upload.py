"""Uploads enter the existing Knowledge pipeline, not Equipment parsing."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from knowledge.source_api import install_source_routes
from knowledge.source_library import SourceLibrary
from knowledge.source_runtime import SourceIngestionService


@pytest.fixture
def upload_app(tmp_path):
    library = SourceLibrary(tmp_path / "library", tmp_path / "inbox")
    service = SourceIngestionService(library, lambda: None)
    app = FastAPI()
    install_source_routes(app, service_factory=lambda: service)
    return TestClient(app), service


def test_upload_preserves_original_and_queues_knowledge_without_enabling_worker(upload_app):
    client, service = upload_app
    response = client.post("/api/knowledge/sources/upload", params={"filename": "QM Manual.md"},
        content=b"# Qm_Tester\nUse APPLY to confirm the test identifier.\n")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "uploaded" and payload["scheduled"] is False
    assert (service.library.inbox / "QM Manual.md").read_bytes() == b"# Qm_Tester\nUse APPLY to confirm the test identifier.\n"
    sources = service.library.status()["sources"]
    assert len(sources) == 1 and sources[0]["status"] == "discovered"
    assert sources[0]["source_id"] == payload["source_id"]
    assert service.library.search("Qm_Tester")["hits"] == []
    assert service.status()["enabled"] is False


def test_upload_duplicate_is_idempotent_and_different_content_cannot_overwrite(upload_app):
    client, service = upload_app
    kwargs = {"params": {"filename": "manual.txt"}, "content": b"Original manual"}
    first = client.post("/api/knowledge/sources/upload", **kwargs)
    duplicate = client.post("/api/knowledge/sources/upload", **kwargs)
    conflict = client.post("/api/knowledge/sources/upload", params=kwargs["params"], content=b"Changed manual")
    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert first.json()["source_id"] == duplicate.json()["source_id"]
    assert conflict.status_code == 409
    assert (service.library.inbox / "manual.txt").read_bytes() == b"Original manual"


@pytest.mark.parametrize("name", ["../escape.md", "/absolute.pdf", "folder\\manual.pdf", ".secret.txt", "manual.exe"])
def test_upload_rejects_paths_and_unsupported_files(upload_app, name):
    client, service = upload_app
    response = client.post("/api/knowledge/sources/upload", params={"filename": name}, content=b"text")
    assert response.status_code == 422
    assert list(service.library.inbox.iterdir()) == []


def test_upload_rejects_empty_body_and_symlink_destination(upload_app, tmp_path):
    client, service = upload_app
    empty = client.post("/api/knowledge/sources/upload", params={"filename": "empty.txt"}, content=b"")
    assert empty.status_code == 422
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged")
    (service.library.inbox / "manual.txt").symlink_to(outside)
    blocked = client.post("/api/knowledge/sources/upload", params={"filename": "manual.txt"}, content=b"unchanged")
    assert blocked.status_code == 409
    assert outside.read_text() == "unchanged"


def test_accepted_upload_obeys_existing_knowledge_worker_setting(upload_app):
    client, service = upload_app
    service.configure(enabled=True)
    response = client.post("/api/knowledge/sources/upload", params={"filename": "manual.txt"}, content=b"manual")
    assert response.status_code == 200
    assert response.json()["scheduled"] is True


def test_oversized_upload_removes_partial_file(upload_app, monkeypatch):
    import knowledge.source_upload as uploads
    monkeypatch.setattr(uploads, "MAX_SOURCE_BYTES", 4)
    client, service = upload_app
    response = client.post("/api/knowledge/sources/upload", params={"filename": "manual.txt"}, content=b"12345")
    assert response.status_code == 413
    assert list(service.library.inbox.iterdir()) == []


def test_folder_scanner_cannot_admit_incomplete_upload(upload_app):
    _, service = upload_app
    (service.library.inbox / ".source-upload-test.part").write_bytes(b"partial")
    result = service.library.scan()
    assert not result["sources"] and not result["errors"]
