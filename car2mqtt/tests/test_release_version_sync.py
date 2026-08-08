from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_files_are_in_sync():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    config = (ROOT / "config.yaml").read_text(encoding="utf-8")
    match = re.search(r'^version:\s*["\']?([^"\'\n]+)', config, re.MULTILINE)
    assert match, "config.yaml has no version"
    assert match.group(1).strip() == version


def test_docker_uses_supervisor_version_and_architecture():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG BUILD_ARCH" in dockerfile
    assert "ARG BUILD_VERSION" in dockerfile
    assert "${BUILD_ARCH}-base-python" in dockerfile
    assert "CAR2MQTT_VERSION=${BUILD_VERSION}" in dockerfile
    assert "COPY VERSION" not in dockerfile
