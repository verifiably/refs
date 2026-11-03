from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).parents[2]


def test_sdist_round_trip_preserves_registry_and_installs(tmp_path):
    """Catch registry artifacts being selected for wheels but omitted from sdists."""
    uv = shutil.which("uv")
    assert uv is not None, "the documented build/test tool uv is required"
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "UV_CACHE_DIR": str(tmp_path / "cache"),
        "UV_PYTHON_DOWNLOADS": "never",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }

    def run(*args):
        done = subprocess.run(
            args, check=False, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    dist = tmp_path / "dist"
    package = tmp_path / "package"
    package.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copyfile(ROOT / "python" / name, package / name)
    shutil.copytree(ROOT / "python" / "src", package / "src", ignore=shutil.ignore_patterns("__pycache__"))
    # Exercise genuinely ignored data regardless of the enclosing checkout's layout.
    (package / ".gitignore").write_text("src/refs/data/\n", encoding="utf-8")
    run(uv, "build", "--no-config", "--no-sources", "--sdist", str(package), "-o", str(dist))
    [sdist] = dist.glob("*.tar.gz")
    expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "registry").iterdir()}
    with tarfile.open(sdist) as archive:
        archive.extractall(tmp_path / "unpacked", filter="data")
    [source] = (tmp_path / "unpacked").iterdir()
    data = source / "src" / "refs" / "data"
    assert data.is_dir(), "sdist omits the bundled registry"
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.iterdir()} == expected
    assert (source / "src" / "refs" / "py.typed").is_file()

    run(uv, "build", "--no-config", "--no-sources", "--wheel", str(source), "-o", str(dist))
    [wheel] = dist.glob("*.whl")
    project = tomllib.loads((ROOT / "python" / "pyproject.toml").read_text())["project"]
    with zipfile.ZipFile(wheel) as archive:
        assert {
            name.removeprefix("refs/data/"): hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist() if name.startswith("refs/data/")
        } == expected
        assert "refs/py.typed" in archive.namelist()
        [metadata] = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        wheel_metadata = BytesParser().parsebytes(archive.read(metadata))
    sdist_metadata = BytesParser().parsebytes((source / "PKG-INFO").read_bytes())
    for metadata in (sdist_metadata, wheel_metadata):
        assert metadata["Name"] == project["name"]
        assert metadata["Version"] == project["version"]
        assert metadata["Requires-Python"] == project["requires-python"]
        assert {Requirement(d) for d in metadata.get_all("Requires-Dist")} == {
            Requirement(d) for d in project["dependencies"]
        }

    venv = tmp_path / "installed"
    run(uv, "venv", "--no-config", "--python", sys.executable, str(venv))
    python = venv / "bin" / "python"
    run(uv, "pip", "install", "--no-config", "--python", str(python), str(wheel))
    oracle = json.loads((ROOT / "fixtures" / "registry.json").read_text())
    result = json.loads(run(str(python), "-I", "-c", """
import json
import sys
from pathlib import Path
import refs
from refs import Registry, parse
from refs.facet import about_facet
registry = Registry.default()
assert Path(refs.__file__).is_relative_to(sys.prefix)
print(json.dumps([registry.fingerprint, str(parse("PMID:21885717", registry))]))
"""))
    assert result == [oracle["fingerprint"], "pubmed:21885717"]
