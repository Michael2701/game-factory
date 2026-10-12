# Testing

## Policy

- **Everything gets tested.** Every milestone adds tests for what it built and runs the full suite before reporting.
- Prefer deterministic tests (no LLM). LLM-dependent tests are opt-in via `RUN_OLLAMA_TESTS=1`.
- A milestone is not "done" until: full suite green, the milestone's "Done when" command succeeds, and outputs are recorded in its `docs/milestones/Mxx-*.md` file.
- Never weaken or delete a test to make it pass; if a test is wrong, say so in the report.

## Framework

Standard library `unittest` (no extra dependency). Files: `tests/test_*.py`. Run from the project root.

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v                      # fast suite
RUN_OLLAMA_TESTS=1 python -m unittest discover -s tests -v   # + LLM tests
```

## Gates

- `RUN_OLLAMA_TESTS=1` — tests that call the local model (need `ollama serve`).
- `RUN_NPM_TESTS=1` — tests that run a real `npm install` (need network; run in a temp sandbox).

## Prerequisites for LLM tests

- Ollama server running: `ollama serve` (or the Ollama app). Check: `ollama list`.
- Model present: `qwen2.5-coder:14b`. A cold load can take 30–90 s; LLM tests use generous timeouts.
- Long LLM runs: prevent macOS idle sleep, otherwise generation stalls (seen in M6: 15 min at ~1 tok/s): `caffeinate -i python -m unittest discover -s tests` (with `RUN_OLLAMA_TESTS=1`).

## Current tests

| File | Checks | Needs Ollama |
|---|---|---|
| `tests/test_m01_structure.py` | required directories, package `__init__.py`, `smoke_graph.py` unchanged (sha256) | no |
| `tests/test_docs.py` | README sections, ROADMAP lists M1–M20, all CLAUDE.md links resolve, every doc indexed | no |
| `tests/test_schemas.py` | all samples build + JSON round-trip, JSON schema generation, validator negatives (slug, extra keys, task order, FileChange paths/payload, TestResult), `GameFactoryState` as LangGraph state, `scripts/validate_schemas.py` | no |
| `tests/test_prompts.py` | 6 prompts: sections, placeholders, JSON-only rule, safety phrases, example JSON validates against models, strict rendering; gated: planner prompt → qwen → valid GameSpec | gated test only |
| `tests/test_planner.py` | `extract_json`/`parse_model` (incl. JS escapes `\'`/`\d` kept, valid escapes unchanged); `plan_game` with a scripted FakeLLM (valid, fenced, prose, repair ok/fail, LLM exception, bad idea); `planner_node` + StateGraph; runner exit codes; gated: the M4 Done-when command | gated test only |
| `tests/test_task_decomposer.py` | `check_plan` rules (incl. prompt example passes), `decompose` with FakeLLM (semantic/schema errors repaired, repair fail, LLM exception), no files written (project hash snapshot), node + planner→decomposer StateGraph, runner exit codes; gated: M5 Done-when command | gated test only |
| `tests/test_safe_tools.py` | path guard (outside, `~`, symlinks, NUL), protected paths, write roots, size limits, list_files hiding, command allowlist + normalisation, ~35 rejected commands, build-script allowlist, real runs in a temp sandbox (exit codes, timeout, truncation, env scrubbing, offline `npm install`), `scripts/test_safe_tools.py` | no |
| `tests/test_graph.py` | (since M19 on top of the Phaser template: `sample_template_task_plan`, template files as coder context, only agents' changes in `proposed_changes`, applied project = template + proposals, scratch mode via `template=None`) 4-node dry-run graph with FakeLLM (7 scripted replies): happy path → `changes_proposed`, coder sees earlier files + may update main.ts, test writer sees the virtual project, failure at each stage stops the graph (partial proposals kept), Ollama down, structure, import side effects, output sections, CLI exit codes + filesystem proof, no files written; **apply flow in a temp root** (M14): apply graph structure, final project written to `generated/<slug>` (latest main.ts, tests), dry run writes nothing + hint, upstream error skips apply, `--target-dir`, bad targets refused before any LLM call (exit 2), existing target refused, `--target-dir` needs `--apply`; gated: M13 Done-when command (~4 min) | gated test only |
| `tests/test_applier_node.py` | `final_changes` (create→update chain merged, delete), `check_target` (new/empty ok; non-empty, file, `templates/`, bare roots, outside, `~`, protected → rejected), `apply_node` in a temp root (default/explicit target, nothing else written, non-empty target and bad targets refused, unsafe proposals — `..`, `.env`, bad package.json, too large — reject everything) | no |
| `tests/test_coder.py` | `check_changes` (paths, coverage, duplicates, create/update by existence, delete, empty, fences, JSON, build script; prompt example passes), `code_task` with FakeLLM (repair, existing files as readable context, NodeError, non-coding tasks skip LLM), no files written, runner exit codes; gated: M8 Done-when command | gated test only |
| `tests/test_apply_changes.py` | applier in a sandbox: dry run writes nothing, create/update/delete, nested/new target folders, whitespace kept, summary, all rejections (paths, target_dir rules, operations, patch, size, package.json), atomicity, coder→applier integration, real project untouched, `scripts/test_apply_changes.py` | no |
| `tests/test_minimal_project.py` | generated files (package.json rules + exact pins, index/main), create/update idempotence, dry run, apply in sandbox, mocked install/build failures, missing dist, bad targets, script; gated `RUN_NPM_TESTS`: real install + build in a sandbox | npm test only |
| `tests/test_test_writer.py` | `check_tests` (file rules, imports, forbidden non-deterministic calls, ≥3 tests, goto URL, hooks; prompt example passes), `write_tests` with FakeLLM (repair, NodeError, project files via format_files), no files written, `file_hashes`, runner exit codes; gated: M11 Done-when command | gated test only |
| `tests/test_test_runner.py` | `run_project_checks` with mocked commands (statuses, stop at first failure, timeout/SafetyError, steps), Playwright JSON parsing, failure message cleanup, node state updates, script; gated `RUN_NPM_TESTS`: real minimal project passes, broken build fails with the vite error, **real Playwright run** (1 pass + 1 deliberate fail) | npm tests only |
| `tests/test_fixer.py` | broken fixtures (one bug each, `is_fixed`), `mentioned_paths`/`relevant_files`, `check_fix` (minimal ok, empty ok, every rejection, creatable files, ≤ 3 files, duplicates, tests not weakened), `fix` with FakeLLM (prompt: relevant content only + project tree + compact TestResult; repair; NodeError; empty), `fixer_node` in a temp root (attempt counter, no LLM when passed/error/exhausted/no target, nothing written), `scripts/run_fixer_dry_run.py` (plausible / implausible / no fix / --json); gated: real qwen fixes every synthetic case | gated test only |
| `tests/test_fix_loop.py` | `apply_fix_node` in a temp root (applies inside the existing project, all-or-nothing, refusals: no fix / no target / outside / bare `generated` / missing / traversal), test runner uses `target_dir`, loop graph structure + recursion limit, `run_fix_loop` with FakeLLM and `FakeChecks` (judges the project on disk): pass first time (no LLM), fail → fix → pass, two bugs → two rounds (round 2 sees the new failure), attempts exhausted (8 rounds), 0 attempts, runner error, no safe fix, fixer NodeError, apply_fix rejection; CLI `--fix-loop` end to end + flag validation; `scripts/run_fix_loop.py` (case written + fixed, existing target refused before anything, outside dir refused, `--project-dir --json`); gated `RUN_OLLAMA_TESTS` + `RUN_NPM_TESTS`: **real loop fixes the two-bugs fixture**. Since M17 every loop that ends passed / exhausted also runs the reviewer, so scripted replies end with a review (`APPROVE` / `REJECT_BUILD` / `NEEDS_CHANGES` from `test_reviewer`); runner error → no review. Since M18 the loop ends at the human gate: final status `needs_human_review`, outcome in `test_result`; CLI prints `=== HUMAN REVIEW ===` | gated test only |
| `tests/test_reviewer.py` | `review_facts` (passing fixture, build failed, build not run, hooks missing in tests, layout), `files_summary` (tree + budget, src first), every `check_review` rule incl. prompt example valid and **example copied verbatim is caught**, missing-file issues allowed, suggestions may name new files; `review` with FakeLLM (first try + prompt content, fenced, repair success/failure, LLM exception, empty project → 0 calls); `reviewer_node` (sets review, keeps status, writes nothing; missing input → 0 calls; NodeError); `scripts/run_reviewer.py` (exit 0/1/2, `--spec`, `--json`); gated `RUN_OLLAMA_TESTS`: real review of the passing fixture (6 checks, hooks pass) and of a build failure (`reject`) | gated test only |
| `tests/test_human_gate.py` | `human_gate_node` (stops at `needs_human_review`, state saved inside the project and loads back equal, failed tests also gated, old decision cleared, missing input / bad / missing target → error and nothing written), `decide` (3 transitions + round trip, approve refused with failed tests, decision only once / only from the gate, unknown decision), `next_actions` per status, `format_gate`, save/load errors, `.factory/` skipped by `read_project`, graph stops at the gate (no LLM call after it), reviewer error → no gate, `gate_passed`; `scripts/decide.py` (`--show`, decide once then exit 2 with the file unchanged, approve refused, missing/invalid state exit 1, bad dir exit 2, usage errors) | — (fast only) |
| `tests/test_phaser_template.py` | template layout, exact pins, `import * as Phaser` everywhere, hook contract, template smoke tests pass `check_tests`, guide names every file; `instantiate` (slug/title, html-escaped), `template_changes`, `project_base`; locks: coder rejects locked files and every Phaser default-import form, decomposer rejects locked targets and needs no `config` task with a template; `final_changes` = template + proposals (none without template); `scripts/new_from_template.py` (writes, refused targets, `--check` failure exit 1); gated `RUN_NPM_TESTS`: **a project from the template really builds and passes 3/3** | gated test only |
| `tests/test_phaser_pitfalls.py` | M20 real-run regressions: `phaser_problems` (Phaser 2 key events, unloaded textures; coder rejects, fixer rejects only what it adds), prompts carry the Phaser notes, API call before boot rejected, template scene getter = last active scene, no visible GameScene placeholder, `normalize_test_code` (scene expect → wait, boot wait inserted only where needed, idempotent), `write_tests` normalizes before checking (no repair call), `attempt_history` reaches the fixer prompt | — (fast only) |
| `tests/test_smoke_graph.py` | `python agents/smoke_graph.py` exits 0 and prints SPEC + REVIEW | yes |

## Adding tests

- One file per milestone area, e.g. `tests/test_schemas.py` (M2), `tests/test_safe_tools.py` (M6).
- Use sample data from `agents/schemas/examples.py` rather than new fixtures.
- LLM nodes: use `FakeLLM` from `tests/fakes.py` (`from fakes import FakeLLM`; see [NODES.md](NODES.md)).
- File/command tools: pass `root=<tempdir>` (see the `Sandbox` base class in `tests/test_safe_tools.py`) — tests must never write into the real project.
- Nodes that must not write files: compare `agents.tools.filesystem.file_hashes()` before/after (older tests use `project_snapshot()` from `tests/test_task_decomposer.py`).
- Tests import project code via `sys.path.insert(0, ROOT)`; tests using shared helpers (`fakes.py`) also insert `ROOT / "tests"` so the module runs alone: `python -m unittest tests.test_graph`.
- Code that runs an LLM or a graph at import time (like `smoke_graph.py`) is tested via `subprocess`, never imported.
- LLM tests: guard with `@unittest.skipUnless(os.environ.get("RUN_OLLAMA_TESTS") == "1", ...)` and assert on structure (valid schema), not exact text.
- Update the table above when adding a test file.
