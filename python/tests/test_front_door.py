from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load_tt_module(tt_path: Path):
    loader = importlib.machinery.SourceFileLoader("refs_tt", str(tt_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


MARKER_SCRIPT = """\
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
root = Path.cwd()
with (root / "markers.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")

stdin_data = sys.stdin.read()
if stdin_data:
    (root / "stdin.txt").write_text(stdin_data, encoding="utf-8")

allowed_git = {
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
}
leaked = sorted(k for k in os.environ if k.startswith("GIT_") and k not in allowed_git)
(root / "child_git_env.json").write_text(json.dumps(leaked), encoding="utf-8")

kind = args[0] if args else ""
if os.environ.get("FAIL_TARGET") == kind:
    sys.stderr.write(f"{kind} failed\\n")
    sys.exit(7)

junit_xml = (
    '<testsuite tests="1" skipped="0" failures="0" errors="0">'
    '<testcase classname="tests.test_sample" name="test_ok" time="0.01"/>'
    "</testsuite>\\n"
)

if kind in {"fast", "suite"}:
    junit_dir = os.environ.get("TT_JUNIT_DIR")
    if not junit_dir:
        sys.stderr.write("run through tt\\n")
        sys.exit(2)
    (Path(junit_dir) / "pytest.xml").write_text(junit_xml, encoding="utf-8")
    print("1 passed in 0.01s")
elif kind == "ci-pytest":
    ev_dir = os.environ.get("REFS_CI_EVIDENCE_DIR")
    if not ev_dir:
        sys.stderr.write("missing REFS_CI_EVIDENCE_DIR\\n")
        sys.exit(2)
    Path(ev_dir).mkdir(parents=True, exist_ok=True)
    (Path(ev_dir) / "pytest.xml").write_text(junit_xml, encoding="utf-8")
    print("1 passed in 0.01s")
elif kind == "ci-vitest":
    ev_dir = os.environ.get("REFS_CI_EVIDENCE_DIR")
    if not ev_dir:
        sys.stderr.write("missing REFS_CI_EVIDENCE_DIR\\n")
        sys.exit(2)
    Path(ev_dir).mkdir(parents=True, exist_ok=True)
    (Path(ev_dir) / "vitest.xml").write_text(junit_xml, encoding="utf-8")
    print("Tests  1 passed (1)")
elif kind in {"one-py", "one-ts"}:
    print("1 passed in 0.01s")
"""


class FrontDoor:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.repo = base / "repo"
        self.bin_dir = base / "bin"
        self.home = base / "home"
        self.config = base / "config"
        self.data = base / "data"
        self.cache = base / "cache"
        self.state = base / "state"
        self.tmp = base / "tmp"
        for directory in (
            self.repo,
            self.bin_dir,
            self.home,
            self.config,
            self.data,
            self.cache,
            self.state,
            self.tmp,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        ssh_stub = self.bin_dir / "ssh"
        ssh_stub.write_text(
            '#!/bin/sh\nprintf "serveraliveinterval %s\\n" "${SSH_INTERVAL:-60}"\n',
            encoding="utf-8",
        )
        ssh_stub.chmod(0o755)

        just_bin = shutil.which("just")
        assert just_bin is not None, "just binary is required on PATH"
        just_dir = str(Path(just_bin).resolve().parent)

        self.tt_log = self.data / "ops" / "runs.jsonl"
        self.env: dict[str, str] = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.data),
            "XDG_CACHE_HOME": str(self.cache),
            "XDG_STATE_HOME": str(self.state),
            "TMPDIR": str(self.tmp),
            "PATH": f"{self.bin_dir}:{just_dir}:/usr/bin:/bin",
            "TT_LOG": str(self.tt_log),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GH_TOKEN": "fake-gh-token-for-test",
            "GITHUB_TOKEN": "fake-github-token-for-test",
        }

        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(self.repo)],
            env=self.env,
            check=True,
        )
        self.assert_git_isolated()

        (self.repo / "tools").mkdir(parents=True, exist_ok=True)
        (self.repo / ".githooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "tools" / "tt", self.repo / "tools" / "tt")
        shutil.copy2(
            REPO / ".githooks" / "pre-commit",
            self.repo / ".githooks" / "pre-commit",
        )
        shutil.copy2(
            REPO / ".githooks" / "pre-push",
            self.repo / ".githooks" / "pre-push",
        )
        (self.repo / ".githooks" / "pre-commit").chmod(0o755)
        (self.repo / ".githooks" / "pre-push").chmod(0o755)

        (self.repo / "marker.py").write_text(MARKER_SCRIPT, encoding="utf-8")
        self.install_justfile()
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "."],
            env=self.env,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "init"],
            env=self.env,
            check=True,
        )

    def assert_git_isolated(self) -> None:
        top = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--show-toplevel"],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_dir = Path(
            subprocess.run(
                ["git", "-C", str(self.repo), "rev-parse", "--absolute-git-dir"],
                env=self.env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ).resolve()
        assert Path(top).resolve() == self.repo.resolve()
        assert git_dir.is_relative_to(self.repo.resolve())

    def install_justfile(self, ci_suite_refs: str | None = None) -> None:
        text = (REPO / "justfile").read_text(encoding="utf-8")
        replacements = {
            "fast_cmd": '"python3 marker.py fast"',
            "test_cmd": '"python3 marker.py suite"',
            "one_cmd": (
                '"if [ \\"$1\\" = ts ]; then shift; python3 marker.py one-ts \\"$@\\"; '
                'else python3 marker.py one-py \\"$@\\"; fi"'
            ),
            "check_hygiene_cmd": '"python3 marker.py hygiene"',
            "check_code_cmd": '"python3 marker.py code"',
            "docs_check_cmd": '"python3 marker.py docs-hygiene"',
            "ci_hygiene_cmd": '"python3 marker.py ci-hygiene"',
            "ci_py_test_cmd": '"python3 marker.py ci-pytest"',
            "ci_ts_test_cmd": '"python3 marker.py ci-vitest"',
            "py_check_cmd": '"python3 marker.py py-check"',
            "ts_check_cmd": '"python3 marker.py ts-check"',
        }
        if ci_suite_refs is not None:
            replacements["ci_suite_refs"] = json.dumps(ci_suite_refs)
        for name, value in replacements.items():
            text = re.sub(
                rf"(?m)^{re.escape(name)}\s*:=\s*.*$",
                lambda _m, n=name, v=value: f"{n} := {v}",
                text,
            )
        (self.repo / "justfile").write_text(text, encoding="utf-8")

    def write_policy(
        self,
        *,
        automatic_broad: object = False,
        broad_targets: list[str] | None = None,
    ) -> None:
        if broad_targets is None:
            broad_targets = [
                "test",
                "test-fast",
                "check-code",
                "ci-python",
                "ci-typescript",
            ]
        raw_bool = (
            "false"
            if automatic_broad is False
            else "true"
            if automatic_broad is True
            else json.dumps(automatic_broad)
        )
        content = (
            f"automatic_broad = {raw_bool}\n"
            f"broad_targets = {json.dumps(broad_targets)}\n"
        )
        (self.repo / ".tt.toml").write_text(content, encoding="utf-8")

    def clear_logs(self) -> None:
        for path in (
            self.repo / "markers.jsonl",
            self.repo / "stdin.txt",
            self.repo / "child_git_env.json",
            self.tt_log,
        ):
            path.unlink(missing_ok=True)

    def run(
        self,
        cmd: list[str],
        *,
        extra_env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.assert_git_isolated()
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            cmd,
            cwd=self.repo,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    def markers(self) -> list[list[str]]:
        path = self.repo / "markers.jsonl"
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def records(self) -> list[dict[str, object]]:
        if not self.tt_log.is_file():
            return []
        return [
            json.loads(line)
            for line in self.tt_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


@pytest.fixture
def front_door(tmp_path: Path) -> FrontDoor:
    return FrontDoor(tmp_path)


def test_fixture_environment_is_isolated(front_door: FrontDoor, tmp_path: Path) -> None:
    expected_keys = {
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "TMPDIR",
        "PATH",
        "TT_LOG",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "LANG",
        "LC_ALL",
        "GH_TOKEN",
        "GITHUB_TOKEN",
    }
    assert set(front_door.env) == expected_keys
    assert Path(front_door.env["HOME"]).is_relative_to(tmp_path.resolve())
    assert Path(front_door.env["TT_LOG"]).is_relative_to(tmp_path.resolve())
    assert front_door.env["GH_TOKEN"] == "fake-gh-token-for-test"
    assert front_door.env["GITHUB_TOKEN"] == "fake-github-token-for-test"
    assert not any(k.startswith("TASKS_") for k in front_door.env)


def test_recipes_match_shared_contract(front_door: FrontDoor) -> None:
    res = front_door.run(["just", "--summary"])
    assert res.returncode == 0, res.stderr
    recipes = set(res.stdout.split())
    expected = {
        "test-fast",
        "test-one",
        "test",
        "test-full",
        "check-hygiene",
        "check-code",
        "check",
        "gate",
        "docs",
        "setup",
        "registry-vendor",
        "registry-sync",
        "registry-check",
        "hook-pre-commit",
        "hook-pre-commit-docs",
        "hook-pre-push",
        "hook-pre-push-fast",
        "ci-python",
        "ci-typescript",
    }
    assert expected <= recipes


@pytest.mark.parametrize(
    ("paths", "expected_target"),
    [
        (("README.md",), "hook-pre-commit-docs"),
        (("AGENTS.md",), "hook-pre-commit-docs"),
        (("docs/STANDARD.md",), "hook-pre-commit-docs"),
        (("fixtures/registry.json",), "hook-pre-commit"),
        (("registry/SOURCES.toml",), "hook-pre-commit"),
        (("README.md", "python/src/refs/__init__.py"), "hook-pre-commit"),
        (("justfile",), "hook-pre-commit"),
    ],
)
def test_pre_commit_routes_docs_paths_only_when_every_staged_file_matches(
    front_door: FrontDoor,
    paths: tuple[str, ...],
    expected_target: str,
) -> None:
    for path in paths:
        target_file = front_door.repo / path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with target_file.open("a", encoding="utf-8") as handle:
            handle.write("\n# changed\n")
        assert front_door.run(["git", "add", "--", path]).returncode == 0

    front_door.clear_logs()
    res = front_door.run([str(front_door.repo / ".githooks" / "pre-commit")])
    assert res.returncode == 0, res.stderr
    rows = front_door.records()
    if expected_target == "hook-pre-commit-docs":
        assert [row["target"] for row in rows] == ["hook-pre-commit-docs"]
        assert front_door.markers() == [["docs-hygiene"]]
    else:
        assert [row["target"] for row in rows] == ["hook-pre-commit", "check-code"]
        assert front_door.markers() == [["hygiene"], ["code"]]


@pytest.mark.parametrize(
    ("recipe", "expected_ran", "expected_skipped"),
    [
        ("check", ["check-hygiene"], ["check-code"]),
        ("gate", ["check-hygiene"], ["check-code", "test"]),
        ("hook-pre-commit", ["hook-pre-commit"], ["check-code"]),
        ("hook-pre-commit-docs", ["hook-pre-commit-docs"], []),
        ("hook-pre-push", ["hook-pre-push"], ["check-code", "test"]),
        ("hook-pre-push-fast", ["hook-pre-push-fast"], ["check-code", "test-fast"]),
    ],
)
def test_policy_off_keeps_hygiene_and_skips_broad_children(
    front_door: FrontDoor,
    recipe: str,
    expected_ran: list[str],
    expected_skipped: list[str],
) -> None:
    front_door.write_policy(automatic_broad=False)
    front_door.clear_logs()

    res = front_door.run(["just", recipe])
    assert res.returncode == 0, res.stderr

    expected_marker = (
        ["docs-hygiene"] if recipe == "hook-pre-commit-docs" else ["hygiene"]
    )
    assert front_door.markers() == [expected_marker]

    rows = front_door.records()
    ran_targets = [r["target"] for r in rows if r["execution"] == "ran"]
    assert ran_targets == expected_ran

    skipped_rows = [r for r in rows if r["execution"] == "skipped"]
    assert [r["target"] for r in skipped_rows] == expected_skipped
    for row in skipped_rows:
        assert row["execution_reason"] == "policy-disabled"
        assert row["exit"] is None
        assert row["tests"] is None
        assert row["selection"] is None
        assert row["slowest"] is None


def test_enabled_hooks_run_hygiene_then_broad_children_and_stop_on_hygiene_failure(
    front_door: FrontDoor,
) -> None:
    front_door.clear_logs()
    res = front_door.run(["just", "hook-pre-push"])
    assert res.returncode == 0, res.stderr
    assert front_door.markers() == [["hygiene"], ["code"], ["suite"]]

    front_door.clear_logs()
    res_fast = front_door.run(["just", "hook-pre-push-fast"])
    assert res_fast.returncode == 0, res_fast.stderr
    assert front_door.markers() == [["hygiene"], ["code"], ["fast"]]

    front_door.clear_logs()
    res_fail_hygiene = front_door.run(
        ["just", "hook-pre-push"],
        extra_env={"FAIL_TARGET": "hygiene"},
    )
    assert res_fail_hygiene.returncode == 7
    assert front_door.markers() == [["hygiene"]]

    front_door.clear_logs()
    res_fail_code = front_door.run(
        ["just", "hook-pre-push-fast"],
        extra_env={"FAIL_TARGET": "code"},
    )
    assert res_fail_code.returncode == 7
    assert front_door.markers() == [["hygiene"], ["code"]]


def test_test_full_and_forced_gate_override_policy_off(front_door: FrontDoor) -> None:
    front_door.write_policy(automatic_broad=False)

    front_door.clear_logs()
    res = front_door.run(["just", "test-full"])
    assert res.returncode == 0, res.stderr
    assert front_door.markers() == [["suite"]]
    rows = front_door.records()
    assert len(rows) == 1
    assert rows[0]["target"] == "test"
    assert rows[0]["execution"] == "ran"
    assert rows[0]["execution_reason"] == "forced"

    front_door.clear_logs()
    res_fail = front_door.run(
        ["just", "test-full"],
        extra_env={"FAIL_TARGET": "suite"},
    )
    assert res_fail.returncode == 7
    rows_fail = front_door.records()
    assert len(rows_fail) == 1
    assert rows_fail[0]["target"] == "test"
    assert rows_fail[0]["execution"] == "ran"
    assert rows_fail[0]["exit"] == 7

    front_door.clear_logs()
    res_gate = front_door.run(["just", "gate"], extra_env={"TT_FORCE": "1"})
    assert res_gate.returncode == 0, res_gate.stderr
    assert front_door.markers() == [["hygiene"], ["code"], ["suite"]]
    rows_gate = front_door.records()
    assert [
        (r["target"], r["execution"], r["execution_reason"]) for r in rows_gate
    ] == [
        ("check-hygiene", "ran", "forced"),
        ("check-code", "ran", "forced"),
        ("test", "ran", "forced"),
    ]


def test_test_one_runs_under_policy_off_and_preserves_arguments_for_py_and_ts(
    front_door: FrontDoor,
) -> None:
    front_door.write_policy(automatic_broad=False)

    args = ["-k", "a and b", "tests/p q.py", "it's", "$HOME", "renders *"]
    front_door.clear_logs()
    res_py = front_door.run(["just", "test-one", *args])
    assert res_py.returncode == 0, res_py.stderr
    assert front_door.markers() == [["one-py", *args]]
    rows_py = front_door.records()
    assert [(r["target"], r["execution"]) for r in rows_py] == [("test-one", "ran")]

    front_door.clear_logs()
    res_ts = front_door.run(["just", "test-one", "ts", *args])
    assert res_ts.returncode == 0, res_ts.stderr
    assert front_door.markers() == [["one-ts", *args]]
    rows_ts = front_door.records()
    assert [(r["target"], r["execution"]) for r in rows_ts] == [("test-one", "ran")]

    res_no_args = front_door.run(["just", "test-one"])
    assert res_no_args.returncode != 0


@pytest.mark.parametrize(
    ("recipe", "xml_name", "test_marker", "check_marker"),
    [
        ("ci-python", "pytest.xml", "ci-pytest", "py-check"),
        ("ci-typescript", "vitest.xml", "ci-vitest", "ts-check"),
    ],
)
def test_ci_targets_require_absolute_evidence_dir_and_preserve_xml_on_check_failure(
    front_door: FrontDoor,
    tmp_path: Path,
    recipe: str,
    xml_name: str,
    test_marker: str,
    check_marker: str,
) -> None:
    front_door.write_policy(automatic_broad=False)

    front_door.clear_logs()
    res_missing = front_door.run(["just", recipe], extra_env={"TT_FORCE": "1"})
    assert res_missing.returncode == 2
    assert "set REFS_CI_EVIDENCE_DIR" in res_missing.stderr
    assert front_door.markers() == []

    front_door.clear_logs()
    res_rel = front_door.run(
        ["just", recipe],
        extra_env={"TT_FORCE": "1", "REFS_CI_EVIDENCE_DIR": "rel/path"},
    )
    assert res_rel.returncode == 2
    assert "CI evidence path must be absolute" in res_rel.stderr
    assert front_door.markers() == []

    ev_dir = tmp_path / f"ev-{recipe}"
    front_door.clear_logs()
    res_fail_check = front_door.run(
        ["just", recipe],
        extra_env={
            "TT_FORCE": "1",
            "REFS_CI_EVIDENCE_DIR": str(ev_dir),
            "FAIL_TARGET": check_marker,
        },
    )
    assert res_fail_check.returncode == 7
    assert front_door.markers() == [[test_marker], ["ci-hygiene"], [check_marker]]
    assert (ev_dir / xml_name).is_file(), (
        f"{xml_name} must be written before hygiene/static checks so always() steps can inspect it"
    )

    front_door.clear_logs()
    res_ok = front_door.run(
        ["just", recipe],
        extra_env={"TT_FORCE": "1", "REFS_CI_EVIDENCE_DIR": str(ev_dir)},
    )
    assert res_ok.returncode == 0, res_ok.stderr
    assert front_door.markers() == [[test_marker], ["ci-hygiene"], [check_marker]]
    assert (ev_dir / xml_name).is_file()


@pytest.mark.parametrize(
    "target",
    [
        "test",
        "test-fast",
        "check-code",
        "ci-python",
        "ci-typescript",
        "hook-pre-push-fast",
    ],
)
def test_hosted_broad_targets_without_force_fail_loudly(
    front_door: FrontDoor,
    target: str,
    tmp_path: Path,
) -> None:
    front_door.write_policy(automatic_broad=False)
    ev_dir = tmp_path / "ev"

    front_door.clear_logs()
    res = front_door.run(
        ["just", target],
        extra_env={
            "GITHUB_ACTIONS": "true",
            "REFS_CI_EVIDENCE_DIR": str(ev_dir),
        },
    )
    assert res.returncode == 2
    assert "TT_FORCE=1" in res.stderr
    assert not any(r["execution"] == "skipped" for r in front_door.records())

    front_door.clear_logs()
    res_forced = front_door.run(
        ["just", target],
        extra_env={
            "GITHUB_ACTIONS": "true",
            "TT_FORCE": "1",
            "REFS_CI_EVIDENCE_DIR": str(ev_dir),
        },
    )
    assert res_forced.returncode == 0, res_forced.stderr
    assert len(front_door.markers()) >= 1


def test_pre_push_routes_refs_and_warns_only_on_uncovered_skipped_push(
    front_door: FrontDoor,
) -> None:
    front_door.write_policy(automatic_broad=False)
    front_door.install_justfile(ci_suite_refs="refs/heads/*")

    oid_a = "a" * 40
    oid_b = "b" * 40
    zero = "0" * 40
    warning_line = (
        "pre-push: local test skipped by policy; remote full-suite coverage is not "
        "declared for this push. Use TT_FORCE=1 for deliberate local verification."
    )

    for ref in ("refs/heads/main", "refs/heads/feat/x"):
        front_door.clear_logs()
        stdin = f"{ref} {oid_a} {ref} {oid_b}\n"
        res = front_door.run(
            [
                str(front_door.repo / ".githooks" / "pre-push"),
                "origin",
                "https://example.invalid/repo.git",
            ],
            stdin=stdin,
        )
        assert res.returncode == 0, res.stderr
        assert warning_line not in res.stderr
        assert (front_door.repo / "stdin.txt").read_text(encoding="utf-8") == stdin
        assert [r["target"] for r in front_door.records()] == [
            "hook-pre-push-fast",
            "check-code",
            "test-fast",
        ]

    front_door.clear_logs()
    del_stdin = (
        f"refs/tags/v1 {zero} refs/tags/v1 {oid_b}\n"
        f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n"
    )
    res_del = front_door.run(
        [
            str(front_door.repo / ".githooks" / "pre-push"),
            "origin",
            "https://example.invalid/repo.git",
        ],
        stdin=del_stdin,
    )
    assert res_del.returncode == 0, res_del.stderr
    assert warning_line not in res_del.stderr
    assert [r["target"] for r in front_door.records()] == [
        "hook-pre-push-fast",
        "check-code",
        "test-fast",
    ]

    uncovered_cases = [
        ("origin", f"refs/tags/v1 {oid_a} refs/tags/v1 {oid_b}\n"),
        (
            "origin",
            (
                f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n"
                f"refs/tags/v1 {oid_a} refs/tags/v1 {oid_b}\n"
            ),
        ),
        ("origin", "malformed-line\n"),
        ("backup", f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n"),
    ]
    for remote, stdin in uncovered_cases:
        front_door.clear_logs()
        res_unc = front_door.run(
            [
                str(front_door.repo / ".githooks" / "pre-push"),
                remote,
                "https://example.invalid/repo.git",
            ],
            stdin=stdin,
        )
        assert res_unc.returncode == 0, res_unc.stderr
        assert warning_line in res_unc.stderr
        assert [r["target"] for r in front_door.records()] == [
            "hook-pre-push",
            "check-code",
            "test",
        ]

    front_door.install_justfile(ci_suite_refs="")
    front_door.clear_logs()
    res_empty = front_door.run(
        [
            str(front_door.repo / ".githooks" / "pre-push"),
            "origin",
            "https://example.invalid/repo.git",
        ],
        stdin=f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n",
    )
    assert res_empty.returncode == 0, res_empty.stderr
    assert warning_line in res_empty.stderr
    assert [r["target"] for r in front_door.records()] == [
        "hook-pre-push",
        "check-code",
        "test",
    ]

    front_door.clear_logs()
    res_forced = front_door.run(
        [
            str(front_door.repo / ".githooks" / "pre-push"),
            "origin",
            "https://example.invalid/repo.git",
        ],
        stdin=f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n",
        extra_env={"TT_FORCE": "1"},
    )
    assert res_forced.returncode == 0, res_forced.stderr
    assert warning_line not in res_forced.stderr


def test_unreadable_policy_refuses_push(front_door: FrontDoor) -> None:
    front_door.write_policy(automatic_broad="no", broad_targets=["test"])
    oid_a = "a" * 40
    oid_b = "b" * 40
    res_uncovered = front_door.run(
        [
            str(front_door.repo / ".githooks" / "pre-push"),
            "origin",
            "https://example.invalid/repo.git",
        ],
        stdin=f"refs/tags/v1 {oid_a} refs/tags/v1 {oid_b}\n",
    )
    assert res_uncovered.returncode == 2
    assert "cannot inspect test execution policy" in res_uncovered.stderr
    assert front_door.markers() == []

    front_door.install_justfile(ci_suite_refs="refs/heads/*")
    res_covered = front_door.run(
        [
            str(front_door.repo / ".githooks" / "pre-push"),
            "origin",
            "https://example.invalid/repo.git",
        ],
        stdin=f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n",
    )
    assert res_covered.returncode == 2
    assert (
        "cannot inspect test execution policy" in res_covered.stderr
        or "expected only boolean automatic_broad and broad_targets" in res_covered.stderr
    )
    assert front_door.markers() == []


def test_missing_keepalive_refuses_before_gate(front_door: FrontDoor) -> None:
    oid_a = "a" * 40
    oid_b = "b" * 40
    res = front_door.run(
        [
            str(front_door.repo / ".githooks" / "pre-push"),
            "origin",
            "git@example.invalid:repo.git",
        ],
        stdin=f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n",
        extra_env={"SSH_INTERVAL": "0"},
    )
    assert res.returncode == 1
    assert "ServerAliveInterval 60" in res.stderr
    assert front_door.markers() == []


def test_pre_push_clears_git_local_environment(front_door: FrontDoor) -> None:
    oid_a = "a" * 40
    oid_b = "b" * 40
    res = front_door.run(
        [
            str(front_door.repo / ".githooks" / "pre-push"),
            "origin",
            "https://example.invalid/repo.git",
        ],
        stdin=f"refs/heads/main {oid_a} refs/heads/main {oid_b}\n",
        extra_env={
            "GIT_DIR": str(front_door.repo / ".git"),
            "GIT_WORK_TREE": str(front_door.repo),
            "GIT_INDEX_FILE": str(front_door.repo / ".git" / "index"),
        },
    )
    assert res.returncode == 0, res.stderr
    leaked = json.loads(
        (front_door.repo / "child_git_env.json").read_text(encoding="utf-8")
    )
    assert leaked == []


def test_ci_workflow_conformance() -> None:
    workflow_path = REPO / ".github" / "workflows" / "ci.yml"
    assert workflow_path.is_file(), "missing .github/workflows/ci.yml"
    text = workflow_path.read_text(encoding="utf-8")

    assert 'branches: ["**"]' in text
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert (
        "if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name != github.repository"
        in text
    )
    assert "group: refs-ci-${{ github.workflow }}-${{ github.ref }}" in text
    assert "cancel-in-progress: true" in text
    assert "contents: read" in text
    assert "timeout-minutes: 15" in text
    assert 'TT_FORCE: "1"' in text
    assert "working-directory: refs" in text

    uses_lines = re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*(\S+)[ \t]*(?:#.*)?$", text)
    assert uses_lines, "no uses: lines found in workflow"
    for ref in uses_lines:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), f"unpinned action ref: {ref}"
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in uses_lines
    assert "astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990" in uses_lines
    assert "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020" in uses_lines
    assert "extractions/setup-just@53165ef7e734c5c07cb06b3c8e7b647c5aa16db3" in uses_lines
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in uses_lines
    assert "setup-python" not in text
    assert 'version: "0.11.29"' in text
    assert 'python-version: ["3.11", "3.13"]' in text
    assert 'node-version: ["20", "24"]' in text

    assert "path: refs" in text
    assert "repository: verifiably/nodes" in text
    assert "path: nodes" in text
    assert "just registry-sync" in text
    assert "npm ci && npm run build" in text
    assert "just ci-python" in text
    assert "just ci-typescript" in text
    assert "python-${{ matrix.python-version }}-coverage" in text
    assert "typescript-${{ matrix.node-version }}-coverage" in text
    assert "retention-days: 30" in text
    assert "if-no-files-found: error" in text
    assert "executed <= 0" in text
    assert "skipped != 0" in text


def assert_policy_and_ci_suite_refs_contract(
    root: Path,
    *,
    env: dict[str, str] | None = None,
) -> None:
    tt = load_tt_module(REPO / "tools" / "tt")
    if env is not None:
        tt._git_env = lambda: {**env, "GIT_OPTIONAL_LOCKS": "0"}
    policy = tt.read_policy(root)
    justfile = root / "justfile"
    ci_suite_refs = subprocess.run(
        ["just", "--justfile", str(justfile), "--evaluate", "ci_suite_refs"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    ci_remote = subprocess.run(
        ["just", "--justfile", str(justfile), "--evaluate", "ci_remote"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert ci_remote == "origin"

    expected_broad = [
        "test",
        "test-fast",
        "check-code",
        "ci-python",
        "ci-typescript",
    ]
    if policy is None:
        assert ci_suite_refs == "", (
            "ci_suite_refs must be empty while .tt.toml is absent"
        )
    elif policy["automatic_broad"] is False:
        assert policy["broad_targets"] == expected_broad
        assert ci_suite_refs == "refs/heads/*"
        wf = root / ".github" / "workflows" / "ci.yml"
        assert wf.is_file(), "policy-off requires .github/workflows/ci.yml"
        wf_text = wf.read_text(encoding="utf-8")
        assert "just ci-python" in wf_text
        assert "just ci-typescript" in wf_text
        assert 'TT_FORCE: "1"' in wf_text
    else:
        assert policy["automatic_broad"] is True
        assert policy["broad_targets"] == expected_broad
        assert ci_suite_refs in {"", "refs/heads/*"}
        if ci_suite_refs == "refs/heads/*":
            wf = root / ".github" / "workflows" / "ci.yml"
            assert wf.is_file(), "Mode B rollback requires .github/workflows/ci.yml"


def test_live_repository_policy_and_ci_suite_refs_contract(
    front_door: FrontDoor,
) -> None:
    assert_policy_and_ci_suite_refs_contract(REPO, env=front_door.env)

    # Stage 1 / Rollback Mode A without .tt.toml (policy=None, ci_suite_refs="")
    (front_door.repo / ".tt.toml").unlink(missing_ok=True)
    front_door.install_justfile(ci_suite_refs="")
    assert_policy_and_ci_suite_refs_contract(front_door.repo, env=front_door.env)

    # Rollback Mode A with .tt.toml (automatic_broad=True, ci_suite_refs="")
    front_door.write_policy(automatic_broad=True)
    front_door.install_justfile(ci_suite_refs="")
    assert_policy_and_ci_suite_refs_contract(front_door.repo, env=front_door.env)

    # Half-configured states must fail AssertionError
    front_door.write_policy(automatic_broad=False)
    front_door.install_justfile(ci_suite_refs="")
    with pytest.raises(AssertionError):
        assert_policy_and_ci_suite_refs_contract(front_door.repo, env=front_door.env)

    (front_door.repo / ".tt.toml").unlink(missing_ok=True)
    front_door.install_justfile(ci_suite_refs="refs/heads/*")
    with pytest.raises(AssertionError):
        assert_policy_and_ci_suite_refs_contract(front_door.repo, env=front_door.env)

    # Activated Stage 2 state and Rollback Mode B state (with workflow present)
    wf_dst = front_door.repo / ".github" / "workflows" / "ci.yml"
    wf_dst.parent.mkdir(parents=True, exist_ok=True)
    wf_dst.write_text(
        'TT_FORCE: "1"\nrun: just ci-python\nrun: just ci-typescript\n',
        encoding="utf-8",
    )
    front_door.write_policy(automatic_broad=False)
    front_door.install_justfile(ci_suite_refs="refs/heads/*")
    assert_policy_and_ci_suite_refs_contract(front_door.repo, env=front_door.env)

    front_door.write_policy(automatic_broad=True)
    front_door.install_justfile(ci_suite_refs="refs/heads/*")
    assert_policy_and_ci_suite_refs_contract(front_door.repo, env=front_door.env)


def test_guides_and_portable_hygiene_conformance(front_door: FrontDoor) -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    install_h2 = readme.find("## Install")
    usage_h2 = readme.find("## Usage")
    assert 0 <= install_h2 < usage_h2
    install_region = readme[install_h2:usage_h2]
    for token in ("just check-hygiene", "just check-code", "just test-full"):
        assert token in install_region

    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    gates_h2 = agents.find("## Gates")
    layout_h2 = agents.find("## Layout")
    assert 0 <= gates_h2 < layout_h2
    gates_region = agents[gates_h2:layout_h2]
    for token in (
        "just test-full",
        "just check-hygiene",
        "just check-code",
        "just ci-python",
        "just ci-typescript",
    ):
        assert token in gates_region

    for cmd in (
        ["python3", "tools/ops-check"],
        ["python3", "tools/ops-docs", "check"],
    ):
        res = subprocess.run(
            cmd,
            cwd=REPO,
            env=front_door.env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, res.stdout + res.stderr
