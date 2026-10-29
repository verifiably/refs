# Front door for tests. Inner loop: `just test-one <runner args>` on the test at hand,
# `just test-fast` (affected-only) before committing. Full suite: `just test`. Gates:
# `just check` at pre-commit, `just gate` at pre-push. The git hooks in .githooks/ call
# `hook-pre-commit` and `hook-pre-push`, which run the very same commands under their own
# target names so the report can price the hooks. Fresh clone:
# `git config core.hooksPath .githooks`.
# Every recipe runs through the vendored timing wrapper tools/tt (source of truth: ops
# bin/tt) so the run is recorded. Design: ops docs/specs/2026-09-04-test-ci-audit-design.md.

set quiet
set positional-arguments

tt := "python3 tools/tt"

# Two packages, so each command is written once per package and the whole-repo commands
# below are composed from them. Recipes, hooks, and CI all run these, so none of the
# three can drift from the others. Each is a subshell: `cd` must not leak to the next.
# Avoid single quotes inside them. The ts commands are empty until the TypeScript package
# lands, and are then composed into fast_cmd, test_cmd and check_cmd below.
# `pytest` is bare on purpose: pyproject's addopts already carries `-q`, and a second
# `-q` is `-qq`, which drops the summary line the wrapper counts tests from.
py_fast_cmd := "(cd python && uv run --frozen pytest --testmon)"
py_test_cmd := "(cd python && uv run --frozen pytest)"
py_check_cmd := "(cd python && uv run --frozen ruff check . && uv run --frozen pyright src)"
py_setup_cmd := "(cd python && uv sync --frozen)"

ts_fast_cmd := ""
ts_test_cmd := ""
ts_check_cmd := ""

# The whole-repo commands are the python ones until the TypeScript package lands. `one_cmd`
# runs inside python/, so its arguments are paths relative to python/.
fast_cmd := py_fast_cmd
test_cmd := py_test_cmd
one_cmd := "cd python && uv run --frozen pytest"
check_cmd := "python3 tools/ops-check && python3 tools/ops-docs check && " + py_check_cmd + " && tasks check"

# What a fresh checkout or worktree needs before the suite can run. Sibling path
# dependencies (../nodes) resolve against the physical checkout dir. In a task worktree
# that dir is under WORK_ROOT, so link the main checkout's sibling there. Idempotent.
setup_cmd := "common=\"$(git rev-parse --git-common-dir)\"; if [ \"$common\" != \".git\" ]; then main=\"$(cd \"$common/..\" && pwd -P)\"; target=\"$main/../nodes\"; link=\"../nodes\"; if [ -L \"$link\" ] && [ \"$(readlink \"$link\")\" = \"$target\" ]; then :; elif [ -e \"$link\" ]; then echo \"setup: $link exists and is not a link to $target\" >&2; exit 1; else ln -s \"$target\" \"$link\"; fi; fi; test -f ../nodes/python/pyproject.toml || { echo \"setup: ../nodes/python/pyproject.toml not found; clone nodes beside this checkout\" >&2; exit 1; }"

# Affected-only: the inner loop. An empty selection is a result, not a failure.
test-fast:
    {{tt}} test-fast -- sh -c '{{fast_cmd}}'

# One file, one test, or a filter, while working on it. Needs at least one argument;
# the whole suite is `test`. The sh -c string never holds the arguments, so quotes, $
# and globs in them reach the runner untouched.
test-one +args:
    {{tt}} test-one -- sh -c '{{one_cmd}} "$@" 2>&1' test-one "$@"

# The full suite, both languages.
test:
    {{tt}} test -- sh -c '{{test_cmd}}'

# Seconds, not minutes: lint, typecheck, and the task-record check.
check:
    {{tt}} check -- sh -c '{{check_cmd}}'

gate: check test

# Render the generated regions of README.md and AGENTS.md from identity.toml. The only
# thing that edits those regions; `check` refuses a commit while they are out of date.
docs:
    {{tt}} docs -- python3 tools/ops-docs write

# Make this checkout runnable. Run once after `git worktree add`; rerun after a
# dependency change.
setup:
    {{tt}} setup -- sh -c '{{setup_cmd}} && {{py_setup_cmd}}'

# What the pre-commit hook runs: `check`'s command under its own hook target.
hook-pre-commit:
    {{tt}} hook-pre-commit -- sh -c '{{check_cmd}}'

# What the pre-push hook runs: the same commands as `gate`, under one hook target.
hook-pre-push:
    {{tt}} hook-pre-push -- sh -c '{{check_cmd}} && {{test_cmd}}'

# CI keeps its two-job matrix once the packages land; each job runs the recipe for its
# package, so the whole job is one recorded number. `tasks check` is not in them: the
# `tasks` binary is not installed on a runner. The typescript recipe is empty until that
# package lands.
ci-python:
    {{tt}} ci-python -- sh -c '{{py_test_cmd}} && {{py_check_cmd}}'

ci-typescript:
    {{tt}} ci-typescript -- sh -c 'true'
