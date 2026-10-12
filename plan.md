You are Claude Code working in this project directory:

/Users/michaelsilianov/Projects/game-factory

We are NOT building a game manually right now.

We are building an agentic system for creating browser games.

The actual games are only target outputs, test fixtures, and validation examples. The main product is the agent system.

Current status:
- Python venv already exists in .venv
- Python version is 3.14.6
- langgraph, langchain, langchain-ollama and pydantic are already installed
- Ollama is installed and working
- Local model qwen2.5-coder:14b is installed and responds correctly
- agents/smoke_graph.py already exists and works
- Node.js and npm are installed
- Git is installed

Main goal:
Build a local LangGraph-based agent system that can eventually take a short game idea and autonomously create a simple browser game project, write files, run tests, fix bugs, review results, and prepare a build artifact.

Tech stack:
Python, LangGraph, LangChain, langchain-ollama, Ollama, qwen2.5-coder:14b, TypeScript, Phaser, Vite, Playwright, Git.

Very important instruction:
Implement milestones strictly in order. Start with Milestone 1. Do not skip ahead. Do not implement a later milestone until all previous milestones are completed and verified. After finishing each milestone, stop and report what was done, what files changed, what commands were run, and whether the milestone is complete. Then wait for my next instruction before starting the next milestone.

Safety rules:
Work only inside /Users/michaelsilianov/Projects/game-factory. Do not access or modify files outside this project. Do not touch ~/.ssh, global config files, work repositories, credentials, .env files outside this project, or system folders. Do not run destructive commands. Do not delete existing files unless explicitly asked. Do not rewrite agents/smoke_graph.py unless explicitly asked. Prefer small safe changes. Before large changes, explain what you are going to do. Use git diff or equivalent summaries to show changes. Keep all agent tools constrained and safe.

Development principles:
The product is the agent system, not one specific game. Prefer working agent loops over manual game implementation. Every milestone must produce a verifiable result. Use deterministic tests where possible. Avoid overengineering. Keep the first version simple, local, and understandable.

Long-term agent pipeline:
User game idea
→ Planner node
→ Structured game spec
→ Task decomposition node
→ Coder node
→ Safe file tools
→ Test writer node
→ Test runner node
→ Fixer node if tests fail
→ Reviewer node
→ Human approval
→ Build artifact
→ Optional portal/publishing later

Target example for validation:
Block Dodger — a simple browser game where the player moves left and right to dodge falling blocks for 60 seconds.

Important:
Block Dodger is not the project. It is only a sample output used later to validate that the agent system works.

Milestone 1 — Agent System Project Skeleton

Objective:
Create the base project structure and documentation for the agentic game factory.

Tasks:
Inspect the current project tree. Keep existing agents/smoke_graph.py unchanged. Create missing directories:
agents/
agents/nodes/
agents/schemas/
agents/tools/
agents/prompts/
games/
templates/
scripts/
docs/
tests/

Create README.md.

README.md must explain:
- This project is an agentic system for creating browser games
- We are not manually building a game yet
- Project goal
- Tech stack
- Current status
- Setup instructions
- How to activate venv
- How to run agents/smoke_graph.py
- Roadmap summary
- Safety rules

Create docs/ROADMAP.md and save this roadmap there in clean Markdown.

Done when:
source .venv/bin/activate
python agents/smoke_graph.py

works successfully, and the project has a clear base structure for an agent system.

After completing Milestone 1:
Show resulting file tree, changed files, command output summary, and any issues found. Then stop. Do not start Milestone 2 until instructed.

Milestone 2 — Core Schemas

Objective:
Define structured data schemas for the agent system.

Create:
agents/schemas/game_spec.py
agents/schemas/task_plan.py
agents/schemas/test_result.py
agents/schemas/review_result.py
agents/schemas/agent_state.py

Schemas should use Pydantic.

Required concepts:
GameIdea
GameSpec
ImplementationTask
TaskPlan
FileChange
CommandResult
TestResult
ReviewResult
GameFactoryState

GameSpec should include:
title, slug, genre, engine, core_loop, scenes, controls, win_condition, lose_condition, test_requirements, asset_requirements, sound_requirements.

GameFactoryState should include:
user_idea, game_spec, task_plan, changed_files, command_results, test_result, review_result, fix_attempts, status.

Done when:
A small script can instantiate and validate these schemas with sample data.

After completing Milestone 2:
Show changed files, validation example, and any issues found. Then stop. Do not start Milestone 3 until instructed.

Milestone 3 — Prompt Templates

Objective:
Create controlled prompts for each planned agent role.

Create:
agents/prompts/planner.md
agents/prompts/task_decomposer.md
agents/prompts/coder.md
agents/prompts/test_writer.md
agents/prompts/fixer.md
agents/prompts/reviewer.md

Important:
Prompts must emphasize structured output, small scope, testability, and safety.

Planner prompt:
Turns a short game idea into a structured GameSpec.

Task decomposer prompt:
Turns GameSpec into a small ordered TaskPlan.

Coder prompt:
Implements one task at a time and only touches allowed files.

Test writer prompt:
Creates deterministic Playwright tests and test hooks.

Fixer prompt:
Fixes only the failing issue based on test output.

Reviewer prompt:
Reviews the result as a simple browser game and returns structured feedback.

Done when:
Prompt files exist and are clear enough to be used by nodes.

After completing Milestone 3:
Show changed files and prompt summary. Then stop. Do not start Milestone 4 until instructed.

Milestone 4 — Planner Node

Objective:
Create the first real LangGraph node: planner_node.

File:
agents/nodes/planner.py

Input:
A short game idea.

Output:
Validated GameSpec object.

Use:
ChatOllama(model="qwen2.5-coder:14b", temperature=0.2)

Use Pydantic validation. Do not accept free text as final output. If the model returns invalid JSON, attempt one repair. If repair fails, return a structured error.

Create a small runner:
scripts/run_planner.py

Done when:
This works:

python scripts/run_planner.py "A simple game where the player dodges falling blocks for 60 seconds."

And prints a valid GameSpec.

After completing Milestone 4:
Show changed files, sample output, validation behavior, and any issues found. Then stop. Do not start Milestone 5 until instructed.

Milestone 5 — Task Decomposer Node

Objective:
Create task_decomposer_node.

File:
agents/nodes/task_decomposer.py

Input:
GameSpec.

Output:
Validated TaskPlan.

The TaskPlan should break game creation into small implementation tasks such as:
- create project structure
- create package.json
- create Vite entry point
- create Phaser scene files
- add test hooks
- add Playwright tests
- run build
- run tests

Important:
This node should not write files. It only creates a plan.

Create runner:
scripts/run_task_decomposer.py

Done when:
Given a sample GameSpec, the node returns a valid ordered TaskPlan.

After completing Milestone 5:
Show changed files, sample task plan, and any issues found. Then stop. Do not start Milestone 6 until instructed.

Milestone 6 — Safe Tool Layer

Objective:
Create safe local tools for file and command operations.

Create:
agents/tools/filesystem.py
agents/tools/commands.py
agents/tools/safety.py

Required functions:
read_file(path)
write_file(path, content)
list_files(path)
ensure_inside_project(path)
run_command(command, cwd)

Safety rules:
Only allow paths inside /Users/michaelsilianov/Projects/game-factory. Reject absolute paths outside project. Reject access to ~/.ssh. Reject dangerous shell commands. Prefer command allowlist. Return stdout, stderr, and exit code.

Allowed commands initially:
npm install
npm run build
npx playwright test
python scripts inside this project
safe listing commands

Do not allow:
rm -rf
sudo
curl pipe shell
writing outside project
reading secrets
changing global configs

Create:
scripts/test_safe_tools.py

Done when:
The test script proves:
- valid project paths work
- outside paths are rejected
- safe commands work
- dangerous commands are rejected

After completing Milestone 6:
Show changed files, safety checks, test output, and any issues found. Then stop. Do not start Milestone 7 until instructed.

Milestone 7 — Graph Skeleton

Objective:
Create the first real LangGraph workflow skeleton.

File:
agents/game_factory_graph.py

Graph:
START
→ planner
→ task_decomposer
→ END

Input:
User idea.

Output:
GameFactoryState containing GameSpec and TaskPlan.

No file writing yet.
No game creation yet.
No tests yet.

Done when:
python agents/game_factory_graph.py

runs the graph and prints:
- parsed GameSpec
- generated TaskPlan
- final state status

After completing Milestone 7:
Show changed files, graph output, and any issues found. Then stop. Do not start Milestone 8 until instructed.

Milestone 8 — Coder Node Dry Run

Objective:
Create coder_node in dry-run mode.

File:
agents/nodes/coder.py

Input:
One ImplementationTask and current state.

Output:
Proposed FileChange objects.

Important:
In this milestone, coder_node must NOT write files directly. It only proposes file changes in structured form.

FileChange should include:
path
operation
content or patch
reason

Create runner:
scripts/run_coder_dry_run.py

Done when:
Given a sample task, coder_node proposes valid FileChange objects without modifying the filesystem.

After completing Milestone 8:
Show changed files, sample proposed file changes, and proof that no files were modified. Then stop. Do not start Milestone 9 until instructed.

Milestone 9 — File Change Applier

Objective:
Create a controlled applier that can apply approved FileChange objects.

Create:
agents/tools/apply_changes.py

Rules:
- Validate all paths
- Apply only inside allowed project folders
- Show a summary before applying
- Support dry_run=True
- Support apply=True
- Return changed file list

Allowed target folders:
games/
templates/
generated/

Done when:
A test script can:
- create a sample FileChange
- show dry-run output
- apply it to a safe test folder
- reject unsafe paths

After completing Milestone 9:
Show changed files, dry-run example, apply example, and safety behavior. Then stop. Do not start Milestone 10 until instructed.

Milestone 10 — Minimal Target Project Generator

Objective:
Create a generator that can create a minimal browser game project structure from structured file changes.

Important:
This is still about the agent system. We are not hand-building a game. We are creating the target output format that agents will later generate.

Target location:
generated/sample-game/

Generated project should be minimal:
package.json
index.html
src/main.ts

It can be a very simple Vite TypeScript placeholder, not a full Phaser game yet.

Done when:
The agent/tooling can generate generated/sample-game/ using FileChange objects and run:

npm install
npm run build

After completing Milestone 10:
Show generated files, build output, and any issues found. Then stop. Do not start Milestone 11 until instructed.

Milestone 11 — Test Writer Node Dry Run

Objective:
Create test_writer_node in dry-run mode.

File:
agents/nodes/test_writer.py

Input:
GameSpec or target project info.

Output:
Proposed Playwright test files as FileChange objects.

Important:
Do not write files directly in the node. It should propose test files.

Tests should prefer deterministic hooks:
window.__GAME_STATE__
window.__TEST_API__

Done when:
The node proposes a valid tests/game.spec.ts file as structured FileChange.

After completing Milestone 11:
Show changed files, sample proposed test file, and any issues found. Then stop. Do not start Milestone 12 until instructed.

Milestone 12 — Command Runner Node

Objective:
Create a node that runs safe commands on generated projects.

File:
agents/nodes/test_runner.py

Use safe command tools.

Required commands:
npm install
npm run build
npx playwright test

Output:
Validated TestResult.

Done when:
The node can run npm build in generated/sample-game/ and return structured CommandResult/TestResult.

After completing Milestone 12:
Show changed files, command results, structured output, and any issues found. Then stop. Do not start Milestone 13 until instructed.

Milestone 13 — End-to-End Dry Run Graph

Objective:
Connect the graph without full autonomous writing yet.

Graph:
START
→ planner
→ task_decomposer
→ coder_dry_run
→ test_writer_dry_run
→ END

Output:
GameFactoryState with:
GameSpec
TaskPlan
proposed file changes
proposed test changes

No actual file writes unless using explicit dry-run preview.

Done when:
A user idea produces a complete dry-run plan for a game project.

After completing Milestone 13:
Show graph output, proposed files, and any issues found. Then stop. Do not start Milestone 14 until instructed.

Milestone 14 — Approved Apply Flow

Objective:
Allow the graph to apply proposed file changes only after explicit approval flag.

Add option:
--apply

Without --apply:
dry run only.

With --apply:
validate and write generated project files.

Done when:
python agents/game_factory_graph.py "game idea"

does dry-run only.

python agents/game_factory_graph.py "game idea" --apply

writes files only inside allowed generated/ or games/ folders.

After completing Milestone 14:
Show dry-run behavior, apply behavior, changed files, and safety checks. Then stop. Do not start Milestone 15 until instructed.

Milestone 15 — Fixer Node

Objective:
Create fixer_node.

Input:
TestResult, relevant files, current GameSpec, current TaskPlan.

Output:
Proposed FileChange objects to fix the issue.

Rules:
- Minimal changes only
- Do not rewrite the whole project
- Do not modify unrelated files
- Respect max_fix_attempts

Done when:
Given a synthetic failing test result, fixer_node proposes a plausible minimal fix.

After completing Milestone 15:
Show changed files, sample fixer input/output, and any issues found. Then stop. Do not start Milestone 16 until instructed.

Milestone 16 — Fix Loop Graph

Objective:
Add controlled fix loop to LangGraph.

Flow:
planner
→ task_decomposer
→ coder
→ apply approved changes
→ test_runner
→ if failed and fix_attempts < 5: fixer
→ apply fix
→ test_runner
→ else stop

For this milestone, use generated/sample-game or a small controlled fixture.

Done when:
A deliberately broken generated project can be fixed through the loop at least once.

After completing Milestone 16:
Show graph behavior, failing result, fix attempt, final result, and any issues found. Then stop. Do not start Milestone 17 until instructed.

Milestone 17 — Reviewer Node

Objective:
Create reviewer_node.

Input:
GameSpec, generated files summary, TestResult.

Output:
ReviewResult.

Reviewer should check:
- Is scope small?
- Is the game testable?
- Are test hooks present?
- Is output suitable for a simple browser game?
- Are there obvious UX issues?
- Are files organized correctly?

Done when:
reviewer_node returns structured ReviewResult.

After completing Milestone 17:
Show changed files, sample review output, and any issues found. Then stop. Do not start Milestone 18 until instructed.

Milestone 18 — Human Approval Gate

Objective:
Add a human approval state.

States:
tests_passed
needs_human_review
approved
rejected
needs_changes

The system should clearly print next possible actions.

Done when:
The graph reaches a human review state and stops.

After completing Milestone 18:
Show changed files, sample state, and any issues found. Then stop. Do not start Milestone 19 until instructed.

Milestone 19 — Phaser Template as Agent Output Target

Objective:
Introduce Phaser/Vite/TypeScript as a real target format for generated games.

Important:
Do not manually build a complete game. Create a target template/spec that the agents can generate or instantiate.

Create:
templates/phaser-vite-template/

It should be minimal and testable:
package.json
index.html
src/main.ts
src/scenes/
playwright.config.ts
tests/

Done when:
The agent system can use this template as a target for future generated games.

After completing Milestone 19:
Show template files, commands run, build/test status, and any issues found. Then stop. Do not start Milestone 20 until instructed.

Milestone 20 — First Real Generated Game Validation

Objective:
Use the completed agent system to generate the first simple game as validation.

Example:
Block Dodger.

Important:
This is the first milestone where an actual game output is generated. The game is not built manually. It must be produced through the agent pipeline as much as possible.

Done when:
The system generates a simple playable browser game project, runs build/tests, fixes at least simple errors, and reaches human review.

After completing Milestone 20:
Show generated game, tests, changed files, limitations, and next steps.

Now begin with Milestone 1 only. Complete Milestone 1, verify it, report the result, and stop.