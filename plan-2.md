# GAME FACTORY — Studio, Backend, Asset Management & Public Games Portal

## MASTER IMPLEMENTATION PLAN — M22–M36

You are Claude Code working in:

`/Users/michaelsilianov/Projects/game-factory`

Your task is to extend our existing LangGraph-based AI Game Factory into a complete local game creation and publishing platform.

**IMPORTANT: Execute ALL milestones sequentially, automatically, from M22 through M36. Do not wait for user confirmation between milestones.**

After each milestone, run the required tests, fix failures, verify the acceptance criteria, document the result, and immediately proceed to the next milestone.

Only stop if there is a critical blocker that cannot be resolved safely, or if an action requires explicit authorization.

Do not skip milestones. Do not claim success based only on passing unit tests. Verify real functionality.

---

# 1. PROJECT BACKGROUND

We already have a working AI agent orchestration system.

Existing technologies:

- Python 3.14.6
- LangGraph
- LangChain
- Ollama
- Qwen2.5-Coder 14B
- Phaser 3
- TypeScript
- Vite
- Playwright
- Git

The existing system includes:

- Game Planner Agent
- Task Decomposer
- Coder Agent
- Test Writer Agent
- Test Runner
- Fixer Agent and fix loops
- Reviewer Agent
- Human Approval Gate
- Generated game artifacts
- Phaser templates
- Automated validation

Previous milestones M1–M20 implemented the basic agent pipeline.

M21 focuses on making generated games genuinely playable, improving browser-error detection, preventing repeated ineffective fixes, and validating real keyboard interactions.

**Before implementing the new milestones, inspect the actual repository and determine the current implementation state. Do not assume M21 is complete unless the code and tests confirm it. Preserve existing functionality.**

The project is an agentic game creation platform, NOT a single game development project.

Do not manually build individual games as part of this new roadmap.

Games should be produced by the existing agent pipeline. Small deterministic fixtures are allowed for UI and integration testing.

---

# 2. NEW PRODUCT VISION

We want two completely separate user-facing applications sharing one backend.

## Application A — Game Factory Studio

A private management interface where the owner can:

- Create a new game project.
- Enter a game idea or prompt.
- View and edit game specifications.
- Upload custom images and assets.
- Assign assets to individual games.
- Preview and manage uploaded assets.
- Start the autonomous game generation process.
- Select an installed Ollama model.
- Monitor agent execution.
- See current progress and agent activities.
- View execution logs and errors.
- See generated files and test results.
- Open a preview of the generated game.
- Request modifications or regeneration.
- Stop a running job safely.
- Save projects and their history.
- Approve a completed game.
- Publish a game to the public portal.
- Unpublish a game without deleting its source.
- Return later and continue working on existing projects.

This application is an administration and production tool, not a public website.

## Application B — Public Games Portal

A separate website for players.

Users should be able to:

- Browse published games.
- View game thumbnails.
- See game titles and descriptions.
- Open a game page.
- Play HTML5 games directly in the browser.
- Restart games.
- Use supported keyboard and mobile controls.
- Navigate back to the game catalog.

The public portal must not expose development tools, agent configuration, logs, private assets, draft projects, or unpublished games.

## Application C — Backend API and Agent Runtime

A Python backend responsible for:

- Project management.
- Persistent game metadata.
- Asset uploads and storage.
- Asset-to-game associations.
- Game specifications.
- Starting LangGraph workflows.
- Managing background generation jobs.
- Reporting progress and errors.
- Saving generated artifacts.
- Managing game versions.
- Preparing game previews.
- Publishing approved builds.
- Serving public game catalog data.

The backend must use the existing LangGraph system rather than creating another independent generation engine.

---

# 3. ARCHITECTURE

Use these technologies unless the existing repository provides a clearly better compatible implementation.

### Backend

- Python
- FastAPI
- Pydantic
- SQLite for initial persistent metadata storage
- SQLAlchemy with migrations
- Existing LangGraph/LangChain infrastructure
- Existing Ollama integration
- Local filesystem for assets and generated artifacts

Use the existing Python virtual environment. Do not install another Python version.

### Game Factory Studio

- React
- TypeScript
- Vite
- A lightweight, consistent component and styling system
- API communication through typed clients

The interface should look like a proper developer tool, not a demonstration webpage.

### Public Games Portal

- React
- TypeScript
- Vite
- Responsive layouts
- Separate routes and application build

### Browser testing

- Playwright
- Vitest for frontend unit tests
- Pytest for backend tests

### Initial deployment

Everything must work locally on the existing Mac.

No cloud hosting is required in this roadmap.

No Docker dependency should be introduced unless there is a compelling reason.

### Logical architecture

```text
                   GAME FACTORY STUDIO
                   (Private Frontend)
                           |
                           | REST API / SSE
                           v
                      FASTAPI BACKEND
                           |
               +-----------+-----------+
               |           |           |
               v           v           v
          DATABASE      ASSETS      JOB MANAGER
               |           |           |
               |           |           v
               |           |       LANGGRAPH
               |           |           |
               |           |     Ollama / Agents
               |           |           |
               |           +-----------+
               |                       |
               v                       v
          GAME METADATA          GENERATED GAMES
               |                       |
               +-----------+-----------+
                           |
                      PUBLISHING
                           |
                           v
                    PUBLIC GAME PORTAL
                           |
                           v
                    PLAY HTML5 GAMES
```

Separate frontend and backend concerns clearly.

Do not put backend business logic into React components.

Do not put browser UI implementation into LangGraph nodes.

---

# 4. PERSISTENT STORAGE REQUIREMENTS

All game projects must survive application restarts.

Persist at minimum:

### GameProject

- ID
- Name
- Slug
- Description
- Original prompt
- Current game specification
- Creation date
- Modification date
- Current status
- Current draft version
- Published version, if any

### GameAsset

- ID
- Game ID
- Original filename
- Stored filename or storage key
- Asset type
- Assigned role
- File size
- MIME type
- Image dimensions
- Creation date
- Storage path
- Content hash

### GenerationRun

- Run ID
- Game ID
- Selected model
- Status
- Start timestamp
- End timestamp
- Current agent/node
- Current milestone or task
- Progress information
- Error information
- Log location
- Resulting draft version

### GameVersion

- Version ID
- Game ID
- Source location
- Build location
- Associated asset manifest
- Test status
- Review status
- Approval status
- Creation timestamp

### PublishedGame

- Game ID
- Published version
- Published title
- Description
- Thumbnail
- Published artifact location
- Publication timestamp
- Public visibility

Do not store large uploaded images directly in SQLite.

Store files on disk and their metadata in the database.

Use stable IDs and controlled paths.

Preserve existing generated projects and artifacts.

Never delete or overwrite existing generated games while introducing the new architecture.

---

# 5. GLOBAL IMPLEMENTATION RULES

These rules apply to every milestone.

1. Complete milestones strictly in sequence: M22, M23, M24, and so on through M36.

2. After each milestone:
    - Run relevant unit tests.
    - Run integration tests.
    - Run Playwright tests where browser functionality is involved.
    - Run builds and type checks.
    - Fix failures before proceeding.
    - Check existing regression tests.
    - Document the milestone result.

3. Do not stop to ask whether to continue to the next milestone.

4. Do not introduce fake production implementations merely to make tests pass.

5. Mocks and deterministic fixtures may be used in unit tests, but actual workflow integration must also be validated.

6. Preserve all previously working agent functionality.

7. Avoid unnecessary refactoring.

8. Keep the architecture modular and maintainable.

9. Never modify generated game files manually to hide agent failures.

10. Uploaded user assets must not disappear after a generation run, restart, or regeneration.

11. A failed generation must not destroy an earlier successful version.

12. No automatic public publishing. Publishing must be explicitly requested by the user through Studio.

13. Do not commit or push to GitHub without explicit authorization.

14. Do not install a different Python version.

15. Use local Ollama models by default. Do not download large additional models without permission.

16. Do not expose the backend or Studio to external networks by default. Bind to localhost.

17. Do not weaken existing file access restrictions.

18. Do not use arbitrary user-provided paths for filesystem access.

19. Keep uploaded user files separate from generated and disposable build files.

20. For every milestone, provide a concise summary, but continue working automatically.

If a test fails, attempt to correct the implementation. If it cannot be fixed safely, stop with a precise technical blocker rather than silently skipping validation.

---

# M22 — Existing System Audit and Architecture Integration

## Objective

Understand the existing system and design the extension without breaking it.

## Tasks

Inspect:

- Existing LangGraph graph
- Existing agent nodes
- File tools
- Job and execution interfaces
- Current generated directory structure
- Existing test infrastructure
- Existing game publishing capabilities, if any
- M21 implementation status

Determine which existing modules can be reused.

Design the backend and frontend boundaries.

Create an architecture document.

Suggested new structure:

```text
game-factory/
  agents/
  backend/
  studio/
  portal/
  games/
  generated/
  templates/
  storage/
  scripts/
  tests/
  docs/
```

Do not move existing files unnecessarily.

## Tests

Run the existing test suite and record its actual baseline results.

## Acceptance criteria

- Existing functionality is understood and documented.
- New directory responsibilities are defined.
- No regressions.
- Integration points with the existing graph are identified.

---

# M23 — Backend Foundation and Persistent Database

## Objective

Create the backend application and persistent data layer.

## Tasks

Create FastAPI application structure.

Implement:

- Database connection
- SQLAlchemy models
- Schema migrations
- Project model
- Asset model
- Generation run model
- Game version model
- Publishing model
- Health endpoint
- Configuration management

Use SQLite for the initial implementation.

Database files must be stored in a persistent, Git-ignored location.

Add startup configuration and migration handling.

Do not create or reset the database destructively on every startup.

## Tests

Test:

- Backend starts.
- Health endpoint responds.
- Database is created when missing.
- Migrations run correctly.
- Projects persist across application restarts.
- Database records survive server restart.
- Invalid records are rejected.

## Acceptance criteria

A working backend with persistent storage and passing tests.

---

# M24 — Asset Storage and Upload API

## Objective

Create persistent asset management for individual game projects.

## Tasks

Implement API operations for:

- Upload asset.
- List game assets.
- Retrieve asset metadata.
- Display asset.
- Update asset role.
- Delete an asset with confirmation.
- Associate an uploaded asset with a game.

Supported image types initially:

- PNG
- JPEG
- WebP

Do not support SVG uploads initially.

Suggested asset roles:

- Thumbnail
- Game background
- Player sprite
- Enemy sprite
- Obstacle sprite
- UI element
- Decorative image
- Unassigned

An uploaded image must belong to a specific game project.

The same physical image may be reused through controlled references if deduplication is implemented.

Store files in persistent directories with generated safe filenames.

Validate actual file content, not only file extensions.

Enforce configurable size and image-dimension limits.

Prevent path traversal and unsafe file access.

## Tests

Test:

- Valid image upload.
- Invalid file rejection.
- Oversized file rejection.
- Asset association.
- Image retrieval.
- Role reassignment.
- Persistence after backend restart.
- Deleting an asset does not delete unrelated assets.
- Attempts to access files outside storage are rejected.

## Acceptance criteria

Images can be uploaded, saved, retrieved, and associated with game projects through the API.

---

# M25 — Studio Frontend Foundation

## Objective

Create the private Game Factory Studio frontend.

## Tasks

Initialize React + TypeScript + Vite.

Implement:

- Main application layout
- Navigation
- Dashboard
- Games page
- Create Game page
- Game detail route
- API client
- Loading states
- Error handling

Suggested navigation:

```text
Dashboard
Games
Create Game
Generation Runs
Settings
```

Use a clean, modern dark interface suitable for a development tool.

Avoid excessive decorative UI.

Provide useful empty states.

## Tests

- Frontend builds.
- Routes work.
- Navigation works.
- API connectivity is handled.
- Missing backend produces a clear error.
- Playwright smoke tests pass.

## Acceptance criteria

Studio opens in the browser and communicates with the backend.

---

# M26 — Game Project Management UI

## Objective

Allow creating, viewing, editing, and saving game projects.

## Tasks

Implement:

### Game list

Show:

- Game name
- Thumbnail
- Status
- Last modified
- Last generation result
- Published/draft status

### Create Game

Form fields:

- Game title
- Game idea
- Description
- Genre
- Optional additional instructions

Save the project before starting generation.

### Game Workspace

Each game has its own workspace.

Suggested tabs:

```text
Overview
Assets
Generation
Preview
Versions
Logs
```

Allow editing the prompt and game metadata.

## Tests

- Create project.
- Edit project.
- Save changes.
- Reload page.
- Verify changes persist.
- Open an existing game.
- Verify games remain separate.
- Backend API tests.
- Playwright end-to-end tests.

## Acceptance criteria

A user can create a project, leave the website, return, and continue working on it.

---

# M27 — Asset Manager Frontend

## Objective

Implement the image management interface for every game.

## Tasks

Inside the Game Workspace, create an Assets tab.

Features:

- Drag-and-drop uploads
- File picker
- Upload progress
- Thumbnail grid
- Full image preview
- File metadata
- Asset role selection
- Rename display labels
- Delete asset
- Upload error messages

Each uploaded image must appear only in the correct game project unless explicitly shared.

Allow assigning uploaded images as:

- Player
- Background
- Enemy
- UI
- Thumbnail
- Other

A game may have multiple assets of the same role.

Show clear visual feedback when an image is uploaded successfully.

## Tests

Playwright tests must:

1. Open a game.
2. Upload an image.
3. See its preview.
4. Assign its role.
5. Reload the browser.
6. Verify the image and role still exist.
7. Upload an image into a second game.
8. Verify assets remain isolated between projects.

Also test deletion and rejected uploads.

## Acceptance criteria

Asset management works through the real frontend and persists correctly.

---

# M28 — Connect Uploaded Assets to the Agent System

## Objective

Make uploaded assets available to the existing game-generating agents.

This milestone is critical.

Uploaded images must not merely exist in Studio. They must actually be usable by generated games.

## Tasks

Implement an asset manifest for each generation run.

Example:

```json
{
  "game_id": "game-123",
  "assets": [
    {
      "id": "asset-001",
      "role": "player_sprite",
      "path": "assets/player.png"
    },
    {
      "id": "asset-002",
      "role": "background",
      "path": "assets/background.webp"
    }
  ]
}
```

The system must:

- Retrieve selected assets for the game.
- Create a generation-specific asset manifest.
- Supply that manifest to relevant agents.
- Make approved image assets available in the generated game workspace.
- Use stable asset references.
- Preserve original uploaded assets.
- Prevent generated code from referencing nonexistent assets.
- Include assets in the final game build.

Extend the planner/coder prompts where necessary.

The Planner should understand which assets are available.

The Coder should use supplied assets instead of generating placeholders when appropriate.

Missing optional assets should not crash generation.

## Tests

- Manifest generated correctly.
- Assets copied or referenced safely.
- Original images preserved.
- Coder receives asset metadata.
- Build correctly includes supplied assets.
- Invalid asset references are rejected.
- A deterministic generated fixture displays a supplied image.

## Acceptance criteria

An uploaded image can appear inside the generated browser game, not just in the asset manager.

---

# M29 — Agent Generation API and Job Management

## Objective

Allow Studio to start and manage autonomous game generation.

## Tasks

Connect FastAPI to the existing LangGraph runtime.

Do not create a new independent orchestration engine.

Create an adapter around the existing graph entrypoint.

Required API capabilities:

- Start generation.
- Get generation status.
- Get current agent/node.
- Get latest progress.
- Retrieve execution logs.
- Retrieve test results.
- Request cancellation.
- Retrieve final result.

Generation must execute in a managed background worker or subprocess.

Do not run a long Ollama generation synchronously inside an HTTP request.

Persist every run in the database.

Support statuses such as:

```text
queued
planning
coding
testing
fixing
reviewing
needs_human_review
completed
failed
cancelled
```

Handle worker failure and application restart.

Do not allow multiple conflicting generation runs for the same game.

Implement safe cancellation and process cleanup.

Keep the initial concurrency small.

## Tests

- Start generation through API.
- Run record created.
- Status transitions correctly.
- Logs captured.
- Errors stored.
- Cancellation works.
- Duplicate conflicting starts rejected.
- Restart does not silently report abandoned jobs as running.

Use a deterministic test workflow for automated tests.

Also provide a separate integration test using the real LangGraph graph and local Ollama.

## Acceptance criteria

The backend can launch and monitor the existing agent system without a terminal command from the user.

---

# M30 — Generation Control and Live Progress UI

## Objective

Allow the owner to control generation from Studio.

## Tasks

Create a Generation tab.

Features:

- Model selector showing installed/available models.
- Start Generation button.
- Current run status.
- Progress timeline.
- Current agent.
- Current task.
- Live logs.
- Build results.
- Test results.
- Fix attempts.
- Error messages.
- Cancel button.
- Run history.

Use Server-Sent Events or another suitable controlled streaming mechanism.

The UI should survive browser refreshes.

Reopening a running project should display its actual backend status.

Model selector must not trigger automatic downloads.

## Tests

- Start a deterministic run through Studio.
- Verify API receives the request.
- Verify progress appears.
- Refresh the page.
- Verify progress and logs remain available.
- Verify completion state.
- Verify failure display.
- Verify cancellation.

## Acceptance criteria

A user can open Studio, click Generate, and observe the agent system working without using Terminal.

---

# M31 — Generated Game Preview

## Objective

Allow previewing generated games inside Studio.

## Tasks

Provide a Preview tab that can launch a generated HTML5 game.

The backend must expose a controlled preview of draft build artifacts.

Features:

- Start preview.
- Reload preview.
- Display game in iframe.
- Fullscreen option.
- Show game version.
- Display test status.
- Display errors when a preview is unavailable.

Do not pretend that a game is ready if no valid build exists.

Use a sandboxed iframe and appropriately isolated origin/security restrictions.

Generated game scripts must not gain access to Studio credentials, backend internals, or private filesystem paths.

## Tests

- Valid built game loads.
- Invalid build shows an error.
- Real keyboard and pointer input reach the game.
- Preview uses the correct game version.
- Preview does not expose private backend paths.
- A generated Phaser fixture works inside the preview.

## Acceptance criteria

The user can play a draft game directly inside Studio.

---

# M32 — Game Versions and Persistent Generated Artifacts

## Objective

Save generated games and allow regeneration without losing previous work.

## Tasks

Introduce immutable or controlled game version artifacts.

For each successful generation, retain:

- Source files
- Build files
- Asset manifest
- Test results
- Review results
- Generation run reference
- Creation timestamp

Implement a Versions tab.

Allow:

- View versions.
- Preview an existing version.
- Compare metadata.
- Select a version as the current draft.
- Regenerate from an existing project.
- Keep previous successful versions after a failed run.

Uploaded user assets must remain persistent across all versions.

Published games must not change merely because a new draft was generated.

Do not overwrite an earlier published version when creating a new draft.

## Tests

- Generate or create two fixture versions.
- Verify both persist.
- Verify correct source/build association.
- Verify failed generation preserves prior versions.
- Verify versions survive backend restart.
- Verify assets remain available.
- Verify existing published artifacts are unchanged by new drafts.

## Acceptance criteria

Generated games and their versions are saved, retrievable, and not lost during regeneration.

---

# M33 — Approval and Publishing Workflow

## Objective

Allow the owner to approve and publish a game through Studio.

## Tasks

Implement publishing lifecycle:

```text
Draft
→ Generated
→ Tested
→ Needs Review
→ Approved
→ Published
```

Allow explicit user approval.

Publishing must:

- Verify that the selected build exists.
- Verify required tests passed.
- Verify no unresolved critical errors.
- Create a stable published artifact.
- Include necessary assets.
- Store published metadata.
- Make the game visible to the public portal.

Support Unpublish.

Unpublishing must hide a game from the public portal without deleting source files or user assets.

Publishing must not happen automatically from LangGraph.

## Tests

- Publishing an approved fixture works.
- Publishing a failed/unapproved build is rejected.
- Published game appears in public catalog API.
- Unpublished game is hidden.
- Draft games are not exposed through public APIs.
- Updating a draft does not replace a published build.
- Published artifacts survive application restart.

## Acceptance criteria

Studio can publish and unpublish games safely.

---

# M34 — Public Games Portal

## Objective

Create the separate public website.

Location:

`portal/`

## Requirements

Create a responsive browser games portal.

### Homepage

Display published games as cards.

Each card includes:

- Thumbnail
- Title
- Short description
- Genre
- Play button or clickable game link

### Game Page

Display:

- Game title
- Game viewport
- Controls/instructions
- Restart/reload option
- Back to catalog
- Fullscreen option where supported

Use a responsive design suitable for desktop and mobile.

The game should run directly in the browser without requiring users to install anything.

Do not expose Studio functions.

Do not expose unpublished games.

Avoid unnecessary user registration for the public portal.

Keep public game execution isolated from administrative APIs.

## Tests

- Public homepage loads.
- Published game cards appear.
- Draft games do not appear.
- Clicking a card opens the correct game.
- Game loads and runs.
- Real keyboard input works.
- Navigation works.
- Mobile viewport layout works.
- Missing game produces a proper 404.
- Unpublished games are not publicly accessible.

## Acceptance criteria

A visitor can open the public portal and play a published HTML5 game.

---

# M35 — Full End-to-End Integration and Regression Tests

## Objective

Verify that Studio, backend, persistent storage, the agent system, and the public portal work together.

This milestone must validate the complete workflow.

## Required end-to-end scenario

1. Open Game Factory Studio.
2. Create a new game project.
3. Enter a simple game idea.
4. Upload a custom player image.
5. Upload a custom background image.
6. Assign their asset roles.
7. Save the project.
8. Start a generation run.
9. Verify the backend starts the correct LangGraph workflow.
10. Verify the uploaded asset manifest is passed to the generation pipeline.
11. Verify generation status and logs appear in Studio.
12. Verify generated files are saved.
13. Verify build and test results are recorded.
14. Open the game preview.
15. Verify the expected assets are included.
16. Verify browser input works.
17. Verify draft version persistence.
18. Approve the completed version.
19. Publish it.
20. Open the public portal.
21. Verify the game appears in the catalog.
22. Open and play the published game.
23. Reload both applications.
24. Verify all persisted information is still present.
25. Create a new draft and verify the existing published version remains unchanged.

For automated CI-style tests, use a deterministic test agent workflow where needed to ensure repeatability.

However, do not claim real game-generation success from mocked agent responses.

Perform a separate real-model validation using the local Ollama model when available.

The real run should confirm that the actual LangGraph agents can produce a playable Phaser game using uploaded assets.

Use the existing M21 acceptance criteria for game playability.

If the real model run fails, report the actual failure without changing the generated game manually.

## Acceptance criteria

All deterministic integration tests pass.

Real local-model behavior is separately tested and honestly reported.

No fake green status.

---

# M36 — Hardening, Developer Experience and Final Delivery

## Objective

Make the complete local platform reliable and convenient to use.

## Backend hardening

Verify:

- Safe upload processing
- Safe filesystem paths
- Persistent SQLite database
- Reliable run state management
- Proper failure reporting
- Safe cancellation
- No secrets exposed
- No unnecessary internet exposure
- No arbitrary command execution from API inputs
- File access restrictions
- Published/draft isolation
- Game iframe isolation

Studio is private and local-only initially.

Before any future public deployment of Studio or the management API, authentication and authorization must be implemented.

## Frontend hardening

Verify:

- Useful error messages
- Loading indicators
- Disabled duplicate actions
- Empty states
- Responsive UI
- Reliable navigation
- Saved state after refresh
- Upload progress
- Stable preview behavior
- Clear generation status

## Developer experience

Provide one simple way to start the local platform.

Preferred:

```text
./scripts/start-dev.sh
```

This command should launch the necessary backend and frontend development servers, using the existing environment.

Do not automatically launch Ollama if it is already running.

Avoid duplicate server processes.

Provide a corresponding shutdown script or clear cleanup mechanism.

Document local URLs for:

- Game Factory Studio
- Backend API
- Public Games Portal

Use nonconflicting ports selected through configuration.

## Final testing

Run:

- Python backend tests
- Existing LangGraph tests
- Frontend unit tests
- TypeScript checks
- Studio production build
- Portal production build
- Playwright Studio tests
- Playwright public portal tests
- Integration tests
- Relevant existing game-generation regression tests

Do not remove failing tests just to achieve a green result.

Document actual test counts and any skipped tests.

## Final documentation

Update:

- README.md
- Architecture documentation
- API documentation
- Developer startup instructions
- Asset management documentation
- Agent generation workflow documentation
- Publishing workflow documentation

Document persistent storage locations and basic backup/restore procedures.

Create milestone completion reports under:

`docs/milestones/`

Do not commit or push unless explicitly asked.

## Acceptance criteria

The full local system can be started conveniently.

Studio, backend, and public portal operate as separate components.

Projects, uploaded assets, run history, versions, and published artifacts persist correctly.

All required automated tests pass, and real-model validation results are documented.

---

# FINAL PRODUCT ACCEPTANCE CRITERIA

The platform is considered functionally complete when the following user experience works:

**GAME FACTORY STUDIO**

I open a browser and access my private Game Factory Studio.

I create a new game project.

I write a description of the game I want.

I upload images for that game.

I assign images to roles such as player, enemy, background, or thumbnail.

I click Generate.

The backend starts the existing LangGraph agent pipeline.

I can see what the agents are doing.

The agents generate game code, run tests, attempt fixes, and report the result.

I can preview a successfully generated game.

I can come back later and still find the game, its uploaded images, logs, and versions.

I can request regeneration without losing earlier versions.

I decide whether to approve and publish the game.

**PUBLIC GAME PORTAL**

A visitor opens the public games website.

They see the published games with thumbnails.

They select a game.

The game opens directly in the browser.

They can play it using actual supported controls.

They do not see any private Studio functionality.

---

# EXECUTION INSTRUCTIONS — START NOW

1. Inspect the repository and current M21 status.
2. Preserve existing functionality.
3. Begin Milestone M22.
4. Implement it fully.
5. Run its required tests.
6. Fix any failures.
7. Verify acceptance criteria.
8. Write its completion report.
9. Automatically continue to M23.
10. Repeat the same process sequentially through M36.

**DO NOT STOP BETWEEN MILESTONES TO ASK FOR PERMISSION.**

Do not require the user to type "continue" or "next milestone."

Work independently within the project and safety constraints.

Do not start a milestone before the previous one passes its required tests.

If a milestone encounters a genuine unresolved blocker, stop, document it precisely, and do not falsely mark later milestones complete.

Do not publish anything externally, incur paid service costs, download additional large models, or push to GitHub without explicit user authorization.

At the end, provide:

- Milestone completion summary
- Actual test results
- Final project structure
- How to start Studio
- How to start the public portal
- How to create a game
- How to upload images
- How to launch game generation
- How to preview and publish a game
- Known limitations or failed real-model tests

**The goal is not another architectural demonstration. The goal is a working local application where I can manage AI-generated games, upload their assets, run my agents, save everything, and publish playable games to a separate public portal.**