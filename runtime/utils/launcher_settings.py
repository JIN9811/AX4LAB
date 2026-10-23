"""Shared, non-actuating AX4LAB CLI/server settings. Never load the application."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import dotenv_values
import yaml


SUPPORTED_BACKENDS = ('openai', 'nemoclaw', 'ollama', 'vllm')


def normalize_backend_name(value: str | None, default: str = 'vllm') -> str:
    """Preserve the runtime's case-insensitive names and OpenAI aliases."""
    name = str(value or default).strip().lower()
    if name in {'api', 'cloud', 'openai-api'}:
        name = 'openai'
    return name if name in SUPPORTED_BACKENDS else default


def select_backend_name(system_config: Mapping, *,
                        environ: Mapping[str, str] | None = None) -> str:
    """Select once for CLI, serve and direct bootstrap; no imports or I/O."""
    env = os.environ if environ is None else environ
    public = str(env.get('AX4LAB_BACKEND') or '').strip()
    if public:
        selected = normalize_backend_name(public, default='')
        if not selected:
            raise ValueError('AX4LAB_BACKEND must be vllm, nemoclaw, ollama or openai')
        return selected
    system = system_config.get('system') or {}
    runtime_env = system_config.get('runtime_env') or {}
    default = normalize_backend_name(system.get('inference_backend'))
    # Invalid legacy values retain the existing config-default fallback.
    return normalize_backend_name(env.get('AUTONOMOUS_BACKEND')
                                  or runtime_env.get('AUTONOMOUS_BACKEND'), default)


@dataclass(frozen=True)
class LauncherSettings:
    host: str
    port: int
    url: str
    backend: str
    public_backend: bool


def load_launcher_settings(repository_root: Path, runtime_root: Path, *,
                           system_config: Mapping | None = None,
                           environ: Mapping[str, str] | None = None) -> LauncherSettings:
    """Environment > checkout .env > system YAML > safe independent defaults.

    AX4LAB_URL is an explicit client-only override (e.g. a remote reverse proxy).
    Legacy ATR_URL/AUTONOMOUS_HOST/PORT are deliberately not launcher aliases.
    Existing AUTONOMOUS_BACKEND remains a low-level runtime compatibility key.
    """
    env = dict(dotenv_values(Path(repository_root) / '.env'))
    env.update(os.environ if environ is None else environ)
    if system_config is None:
        config_path = Path(runtime_root) / 'configs/system.yaml'
        system_config = yaml.safe_load(config_path.read_text()) if config_path.is_file() else {}
    if system_config is None:
        system_config = {}
    if not isinstance(system_config, Mapping):
        raise ValueError('AX4LAB system configuration must be a mapping')
    server = system_config.get('server') or {}
    host = str(env.get('AX4LAB_HOST') or server.get('host') or '127.0.0.1').strip()
    if not host or any(char.isspace() for char in host) or any(char in host for char in '/?#@'):
        raise ValueError('AX4LAB_HOST must be a host name or IP address')
    port = int(env.get('AX4LAB_PORT') or server.get('port', 7861))
    if not 1 <= port <= 65535:
        raise ValueError('AX4LAB_PORT must be between 1 and 65535')
    connect_host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
    if ':' in connect_host and not connect_host.startswith('['):
        connect_host = '[' + connect_host + ']'
    url = str(env.get('AX4LAB_URL') or f'http://{connect_host}:{port}').strip().rstrip('/')
    parsed = urlsplit(url)
    if (any(char.isspace() for char in url) or parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('AX4LAB_URL must be an HTTP(S) base URL without credentials, query or fragment')
    # Validate malformed explicit ports before making any request.
    _ = parsed.port
    public_backend = bool(str(env.get('AX4LAB_BACKEND') or '').strip())
    backend = select_backend_name(system_config, environ=env)
    return LauncherSettings(host, port, url, backend, public_backend)


def api_base_url() -> str:
    """Select the current checkout's API without initializing runtime state."""
    from utils.runtime_paths import current_paths
    paths = current_paths()
    return load_launcher_settings(paths.repository_root, paths.runtime_root).url


if __name__ == '__main__':
    try:
        settings = load_launcher_settings(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        # Configuration errors may include source secrets: never echo values.
        print('Invalid AX4LAB launcher configuration; check .env and configs/system.yaml.', file=sys.stderr)
        raise SystemExit(2)
    print(settings.url)
    print(settings.backend)
