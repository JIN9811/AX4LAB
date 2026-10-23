"""A second checkout must not clean up the first checkout's video process."""
from pathlib import Path
import shutil


def test_orphan_cleanup_only_terminates_current_checkout_proxy(tmp_path, monkeypatch):
    from app import main
    proc = tmp_path / 'proc'
    owned = proc / '10001'
    foreign = proc / '10002'
    unknown = proc / '10003'
    for target in (owned, foreign, unknown):
        target.mkdir(parents=True)
        (target / 'cmdline').write_bytes(b'ffmpeg\0-i\0rtsps://fixture/streaming/live/1\0-f\0mpjpeg\0pipe:1')
    (owned / 'cwd').symlink_to(main.RUNTIME_PATHS.runtime_root, target_is_directory=True)
    (foreign / 'cwd').symlink_to(tmp_path / 'original/runtime', target_is_directory=True)
    original_path = Path
    monkeypatch.setattr(main, 'Path', lambda value: proc if value == '/proc' else original_path(value))
    killed = []
    def kill(pid, signal):
        killed.append(pid)
        shutil.rmtree(proc / str(pid))
    monkeypatch.setattr(main.os, 'kill', kill)
    main._cleanup_orphan_bambu_video_ffmpeg()
    assert killed == [10001]
    assert foreign.exists() and unknown.exists()
