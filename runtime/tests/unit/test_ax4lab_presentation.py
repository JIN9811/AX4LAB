"""Exercise operator-visible templates without starting runtime/device services."""
from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
import pytest


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = set()
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])

    def handle_data(self, data):
        self.text.append(data)


@pytest.mark.parametrize("replay", [False, True])
def test_live_and_replay_render_ax4lab_brand_without_changing_control_ids(replay):
    templates = Path(__file__).resolve().parents[2] / "web/templates"
    env = Environment(loader=FileSystemLoader(templates), autoescape=True)
    html = env.get_template("planning.html").render(title="Live GUI", replay=replay)
    page = Page(html)
    assert "AX4LAB Runtime" in " ".join(page.text)
    assert {"planning-run-detail", "live-runtime-clock", "planning-chat-status"} <= page.ids
    assert ("replay-run-select" in page.ids) is replay


def test_runtime_ide_render_has_ax4lab_identity_and_preserves_graph_controls():
    templates = Path(__file__).resolve().parents[2] / "web/templates"
    env = Environment(loader=FileSystemLoader(templates), autoescape=True)
    page = Page(env.get_template("runtime_ide.html").render(title="AX4LAB Runtime IDE"))
    assert "<h1>AX4LAB Runtime IDE</h1>" in env.get_template("runtime_ide.html").render()
    assert {"ide-graph-select", "ide-validate-btn", "ide-compile-btn", "ide-dry-run-btn"} <= page.ids
