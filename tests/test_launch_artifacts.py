from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

SENSITIVE_TERMS = {
    "bot tokens",
    "session strings",
    "Business connection IDs",
    "chat IDs",
    "user IDs",
    "message IDs",
    "transcript text",
    "message bodies",
    "audio",
    "video",
    "provider logs",
}


def project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    plugin = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))

    version = pyproject["project"]["version"]
    assert str(plugin["version"]) == version
    return version


def heading_slug(heading: str) -> str:
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.ASCII)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def markdown_heading_slugs(path: Path) -> set[str]:
    slugs: set[str] = set()
    seen: dict[str, int] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue

        base_slug = heading_slug(match.group(1))
        slug_count = seen.get(base_slug, 0)
        seen[base_slug] = slug_count + 1
        slugs.add(base_slug if slug_count == 0 else f"{base_slug}-{slug_count}")

    return slugs


def markdown_links(text: str) -> list[str]:
    return re.findall(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text)


def test_bug_report_issue_form_is_valid_and_requires_privacy_acknowledgements():
    issue_form = yaml.safe_load((ROOT / ".github" / "ISSUE_TEMPLATE" / "bug-report.yml").read_text(encoding="utf-8"))

    assert issue_form["name"] == "Bug report"
    assert issue_form["title"] == "[Bug]: "

    fields = {item["id"]: item for item in issue_form["body"] if "id" in item}
    for field_id in {
        "safety",
        "hermes_version",
        "plugin_version",
        "install_mode",
        "event_direction",
        "media_event_type",
        "cleanup_mode",
        "stt_mode",
        "steps",
        "expected",
        "actual",
        "sanitized_context",
    }:
        assert field_id in fields

    safety_options = fields["safety"]["attributes"]["options"]
    assert len(safety_options) >= 4
    assert all(option["required"] is True for option in safety_options)

    form_text = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug-report.yml").read_text(encoding="utf-8")
    for term in SENSITIVE_TERMS:
        assert term in form_text


def test_landing_bundle_uses_relative_links_and_no_network_assets():
    landing_files = [
        ROOT / "landing" / "README.md",
        ROOT / "landing" / "ASSETS.md",
        ROOT / "landing" / "styles.css",
    ]
    network_pattern = re.compile(r"https?://|//[^\\s)'\"]")

    for path in landing_files:
        text = path.read_text(encoding="utf-8")
        assert not network_pattern.search(text), path

    for path in [ROOT / "landing" / "README.md", ROOT / "landing" / "ASSETS.md"]:
        for target in markdown_links(path.read_text(encoding="utf-8")):
            link_path, _, fragment = target.partition("#")
            assert not re.match(r"[a-z][a-z0-9+.-]*:|//", target, flags=re.IGNORECASE), target
            assert not link_path.startswith("/"), target

            resolved = (path.parent / (link_path or path.name)).resolve()
            assert resolved.is_relative_to(ROOT), target
            assert resolved.exists(), target

            if fragment:
                assert resolved.suffix == ".md", target
                assert fragment in markdown_heading_slugs(resolved), target

    styles = (ROOT / "landing" / "styles.css").read_text(encoding="utf-8")
    assert "@import" not in styles
    assert "url(" not in styles
    assert "prefers-reduced-motion" in styles
    assert "focus-visible" in styles
    assert "color-scheme" in styles


def test_launch_docs_state_current_scope_and_truth_boundaries():
    version = project_version()
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    landing = (ROOT / "landing" / "README.md").read_text(encoding="utf-8")
    assets = (ROOT / "landing" / "ASSETS.md").read_text(encoding="utf-8")

    assert "`enabled: false`" in security
    assert "sanitized public issue" in security
    assert version in security
    assert "uv run --frozen --with pytest --with pytest-asyncio --with pyyaml python -m pytest -q" in contributing
    assert "Ruff is not currently declared" in contributing
    assert "telegram-business-voice-transcriber" in contributing
    assert "business_connection_id" in landing
    assert "ctx.llm" in landing
    assert "STT backend configured in Hermes" in landing
    assert version in landing
    assert "20-Second Synthetic Demo" in assets
    assert "Do not create fake Telegram client screenshots" in assets
