# Front door for tests and checks. Focused work: `just test-one <runner args>`.
# `check` and `gate` compose mandatory hygiene and separately timed broad targets.
# Hooks time hygiene once, then invoke the same broad children. Full suite: `just test`;
# deliberate full suite: `just test-full`. Install hooks with
# `git config core.hooksPath .githooks`.
# Every measured recipe uses the vendored tools/tt (source of truth: ops bin/tt).
# Reference: ops docs/tooling.md and docs/test-execution-policy.md.

set quiet
set positional-arguments

tt := "python3 tools/tt"

# Two packages, so each command is written once per package and the whole-repo commands
# below are composed from them. Recipes, hooks, and CI all run these, so none of the
# three can drift from the others. Each is a subshell: `cd` must not leak to the next.
# Avoid single quotes inside them.
# `pytest` is bare on purpose: pyproject's addopts already carries `-q`, and a second
# `-q` is `-qq`, which drops the summary line the wrapper counts tests from.
py_fast_cmd := "(cd python && uv run --frozen pytest --testmon --junitxml=\"${TT_JUNIT_DIR:?run through tt}/pytest.xml\")"
py_test_cmd := "(cd python && uv run --frozen pytest --junitxml=\"${TT_JUNIT_DIR:?run through tt}/pytest.xml\")"
py_check_cmd := "(cd python && uv run --frozen ruff check . && uv run --frozen pyright src)"
py_setup_cmd := "(cd python && uv sync --frozen)"

ts_fast_cmd := "(cd ts && npm test -- --changed --passWithNoTests)"
ts_test_cmd := "(cd ts && npm test -- --reporter=default --reporter=junit --outputFile.junit=\"${TT_JUNIT_DIR:?run through tt}/vitest.xml\")"
ts_check_cmd := "(cd ts && npm run typecheck && npm run check)"
ts_setup_cmd := "(cd ts && npm ci)"

# `one_cmd` takes its runner arguments as "$@": a first argument of `ts` runs vitest in ts/
# on the rest (paths relative to ts/); anything else goes to pytest in python/ (paths
# relative to python/).
# testmon and `vitest --changed` follow code, not the files tests read, so an edit under
# `data_paths` alone would select nothing: while git shows one uncommitted, `fast_cmd` runs
# the full suite instead. A failing `git status` fails the run rather than reading as clean.
data_paths := "fixtures registry"
fast_cmd := "changed=$(git status --porcelain -- " + data_paths + ") || exit 1; if [ -n \"$changed\" ]; then echo \"test-fast: uncommitted change under " + data_paths + "; running the full suite\" >&2; " + test_cmd + "; else " + py_fast_cmd + " && " + ts_fast_cmd + "; fi"
test_cmd := py_test_cmd + " && " + ts_test_cmd
one_cmd := "if [ \"$1\" = ts ]; then shift; (cd ts && npx --no-install vitest run \"$@\"); else (cd python && uv run --frozen pytest \"$@\"); fi"

# registry/ is the one copy of the vendored registry; each package carries a gitignored copy
# (python/src/refs/data/, ts/data/) that `registry-sync` writes and `registry-check` compares
# with it by sha256, failing on a copy that is missing, extra or different. Subshells, like
# the package commands, so a `;` inside cannot break the `&&` chains they are composed into.
registry_dirs := "python/src/refs/data ts/data"
registry_sync_cmd := "(for d in " + registry_dirs + "; do mkdir -p $d && rm -f $d/* && cp registry/* $d/ || exit 1; done)"
registry_check_cmd := "(want=$(cd registry && sha256sum -- *); for d in " + registry_dirs + "; do have=$(cd $d 2>/dev/null && sha256sum -- *); [ \"$have\" = \"$want\" ] || { echo \"registry-check: $d does not match registry/; run just registry-sync\" >&2; exit 1; }; done)"

# What a fresh checkout or worktree needs before the suite can run. Sibling path
# dependencies (../nodes) resolve against the physical checkout dir. In a task worktree
# that dir is under WORK_ROOT, so link the main checkout's sibling there. Idempotent.
setup_cmd := "common=\"$(git rev-parse --git-common-dir)\"; if [ \"$common\" != \".git\" ]; then main=\"$(cd \"$common/..\" && pwd -P)\"; target=\"$main/../nodes\"; link=\"../nodes\"; if [ -L \"$link\" ] && [ \"$(readlink \"$link\")\" = \"$target\" ]; then :; elif [ -e \"$link\" ]; then echo \"setup: $link exists and is not a link to $target\" >&2; exit 1; else ln -s \"$target\" \"$link\"; fi; fi; test -f ../nodes/python/pyproject.toml || { echo \"setup: ../nodes/python/pyproject.toml not found; clone nodes beside this checkout\" >&2; exit 1; }"

# Broad policy and hosted evidence interfaces. Keep CI ref coverage undeclared until activation.
check_hygiene_cmd := "python3 tools/ops-check && python3 tools/ops-docs check && " + registry_check_cmd + " && tasks check"
check_code_cmd := py_check_cmd + " && " + ts_check_cmd
docs_paths := "*.md docs/*"
docs_check_cmd := check_hygiene_cmd
ci_suite_refs := ""
ci_remote := "origin"
ci_evidence_cmd := "case \"${REFS_CI_EVIDENCE_DIR:-}\" in \"\") echo \"set REFS_CI_EVIDENCE_DIR\" >&2; exit 2;; /*) ;; *) echo \"CI evidence path must be absolute\" >&2; exit 2;; esac"
ci_hygiene_cmd := "python3 tools/ops-check && python3 tools/ops-docs check && " + registry_check_cmd
ci_py_test_cmd := "(cd python && uv run --frozen pytest --junitxml=\"$REFS_CI_EVIDENCE_DIR/pytest.xml\")"
ci_ts_test_cmd := "(cd ts && npm test -- --reporter=default --reporter=junit --outputFile.junit=\"$REFS_CI_EVIDENCE_DIR/vitest.xml\")"

# Affected-only: the inner loop. An empty selection is a result, not a failure.
test-fast:
    {{tt}} test-fast -- sh -c '{{fast_cmd}}'

# One file, one test, or a filter, while working on it: `just test-one tests/test_dialect.py`
# for pytest, `just test-one ts tests/dialect.test.ts` for vitest. Needs at least one
# argument; the whole suite is `test`. The sh -c string never holds the arguments, so quotes,
# $ and globs in them reach the runner untouched.
test-one +args:
    {{tt}} test-one -- sh -c '{{one_cmd}} 2>&1' test-one "$@"

# The full suite, both languages.
test:
    {{tt}} test -- sh -c '{{test_cmd}}'

# Compose mandatory hygiene and policy-controlled static checks.
check:
    just check-hygiene
    just check-code

gate:
    just check
    just test

# Render the generated regions of README.md and AGENTS.md from identity.toml. The only
# thing that edits those regions; `check` refuses a commit while they are out of date.
docs:
    {{tt}} docs -- python3 tools/ops-docs write

# Make this checkout runnable. Run once after `git worktree add`; rerun after a
# dependency change.
setup:
    {{tt}} setup -- sh -c '{{setup_cmd}} && {{py_setup_cmd}} && {{ts_setup_cmd}} && {{registry_sync_cmd}}'

# Vendor a Bioregistry snapshot (the reduced bioregistry.json and its expected sha256) into
# registry/ in the pattern dialect, then copy registry/ into the packages.
registry-vendor snapshot sha256: && registry-sync
    {{tt}} registry-vendor -- uv run --frozen --project python python tools/vendor_registry.py --from-snapshot "$1" --sha256 "$2"

# Copy registry/ into each package's gitignored data directory.
registry-sync:
    {{tt}} registry-sync -- sh -c '{{registry_sync_cmd}}'

# Compare each package's copy of registry/ with it by sha256; `check` runs this too.
registry-check:
    {{tt}} registry-check -- sh -c '{{registry_check_cmd}}'

# Time only mandatory hygiene under the hook target; broad children decide policy separately.
hook-pre-commit:
    {{tt}} hook-pre-commit -- sh -c '{{check_hygiene_cmd}}'
    just check-code

# The uncovered-push route composes the same checks and full suite as `gate`.
hook-pre-push:
    {{tt}} hook-pre-push -- sh -c '{{check_hygiene_cmd}}'
    just check-code
    just test

# CI keeps its two-job matrix once the packages land; each job runs the recipe for its
# package, so the whole job is one recorded number. `tasks check` is not in them: the
# `tasks` binary is not installed on a runner.
ci-python:
    {{tt}} ci-python -- sh -c '{{ci_evidence_cmd}} && {{ci_py_test_cmd}} && {{ci_hygiene_cmd}} && {{py_check_cmd}}'

ci-typescript:
    {{tt}} ci-typescript -- sh -c '{{ci_evidence_cmd}} && {{ci_ts_test_cmd}} && {{ci_hygiene_cmd}} && {{ts_check_cmd}}'

test-full:
    TT_FORCE=1 just test

check-hygiene:
    {{tt}} check-hygiene -- sh -c '{{check_hygiene_cmd}}'

check-code:
    {{tt}} check-code -- sh -c '{{check_code_cmd}}'

hook-pre-commit-docs:
    {{tt}} hook-pre-commit-docs -- sh -c '{{docs_check_cmd}}'

hook-pre-push-fast:
    {{tt}} hook-pre-push-fast -- sh -c '{{check_hygiene_cmd}}'
    just check-code
    just test-fast
