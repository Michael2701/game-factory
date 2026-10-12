"""Block Dodger sample data for every schema (used by scripts and tests).

Each builder returns a fresh, validated object.
"""

from agents.schemas.agent_state import FactoryStatus, GameFactoryState, HumanDecision, LoopStep
from agents.schemas.game_spec import GameIdea, GameSpec
from agents.schemas.review_result import ReviewResult
from agents.schemas.task_plan import FileChange, FileChangeSet, TaskPlan
from agents.schemas.test_result import CommandResult, TestResult

BLOCK_DODGER_IDEA = "A simple game where the player dodges falling blocks for 60 seconds."


def sample_game_idea() -> GameIdea:
    return GameIdea(text=BLOCK_DODGER_IDEA)


def sample_game_spec() -> GameSpec:
    return GameSpec.model_validate({
        "title": "Block Dodger",
        "slug": "block-dodger",
        "genre": "arcade",
        "engine": "phaser",
        "core_loop": "Move left/right to avoid blocks falling from the top; survive 60 seconds.",
        "scenes": [
            {"name": "StartScene", "purpose": "Title and start button"},
            {"name": "GameScene", "purpose": "Gameplay: player, falling blocks, timer"},
            {"name": "GameOverScene", "purpose": "Win/lose message and restart"},
        ],
        "controls": [
            {"input": "ArrowLeft", "action": "move left"},
            {"input": "ArrowRight", "action": "move right"},
        ],
        "win_condition": "Survive for 60 seconds.",
        "lose_condition": "A falling block hits the player.",
        "test_requirements": [
            "window.__GAME_STATE__ exposes scene, timeLeft, isGameOver",
            "window.__TEST_API__ can spawn a block over the player",
            "collision ends the game",
            "timer reaching 0 wins the game",
        ],
        "asset_requirements": ["player rectangle", "block rectangle"],
        "sound_requirements": [],
    })


def sample_task_plan() -> TaskPlan:
    """Plan for a project built from scratch (template=None); see sample_template_task_plan for M19."""
    return TaskPlan.model_validate({
        "game_slug": "block-dodger",
        "tasks": [
            {"id": "T1", "title": "Project structure", "description": "Create folders for the game project.",
             "kind": "setup", "target_files": [], "acceptance": "Folders exist."},
            {"id": "T2", "title": "package.json", "description": "Add Vite, Phaser, Playwright and scripts.",
             "kind": "config", "target_files": ["package.json"], "depends_on": ["T1"],
             "acceptance": "npm install succeeds."},
            {"id": "T3", "title": "Vite entry point", "description": "index.html and src/main.ts booting Phaser.",
             "kind": "code", "target_files": ["index.html", "src/main.ts"], "depends_on": ["T2"],
             "acceptance": "npm run build succeeds."},
            {"id": "T4", "title": "Scenes", "description": "Start, Game and GameOver scenes.",
             "kind": "code", "target_files": ["src/scenes/StartScene.ts", "src/scenes/GameScene.ts",
                                              "src/scenes/GameOverScene.ts"],
             "depends_on": ["T3"], "acceptance": "Game is playable in the browser."},
            {"id": "T5", "title": "Test hooks", "description": "Expose __GAME_STATE__ and __TEST_API__.",
             "kind": "test_hooks", "target_files": ["src/testHooks.ts"], "depends_on": ["T4"],
             "acceptance": "Hooks available on window."},
            {"id": "T6", "title": "Playwright tests", "description": "Tests for start, lose and win.",
             "kind": "tests", "target_files": ["tests/game.spec.ts"], "depends_on": ["T5"],
             "acceptance": "Tests compile."},
            {"id": "T7", "title": "Build", "description": "Run npm run build.",
             "kind": "build", "depends_on": ["T3", "T4"], "acceptance": "Exit code 0."},
            {"id": "T8", "title": "Run tests", "description": "Run npx playwright test.",
             "kind": "run_tests", "depends_on": ["T6", "T7"], "acceptance": "All tests pass."},
        ],
    })


def sample_template_task_plan() -> TaskPlan:
    """Plan on top of the Phaser template (M19): no setup/config tasks, template files are updated."""
    return TaskPlan.model_validate({
        "game_slug": "block-dodger",
        "tasks": [
            {"id": "T1", "title": "Scenes", "description": "Update StartScene and GameScene, create GameOverScene.",
             "kind": "code", "target_files": ["src/scenes/StartScene.ts", "src/scenes/GameScene.ts",
                                              "src/scenes/GameOverScene.ts"],
             "acceptance": "Game is playable in the browser."},
            {"id": "T2", "title": "Test hooks", "description": "Expose __GAME_STATE__ and __TEST_API__.",
             "kind": "test_hooks", "target_files": ["src/testHooks.ts"], "depends_on": ["T1"],
             "acceptance": "Hooks available on window."},
            {"id": "T3", "title": "Playwright tests", "description": "Tests for start, lose and win.",
             "kind": "tests", "target_files": ["tests/game.spec.ts"], "depends_on": ["T2"],
             "acceptance": "Tests compile."},
            {"id": "T4", "title": "Build", "description": "Run npm run build.",
             "kind": "build", "depends_on": ["T1", "T2"], "acceptance": "Exit code 0."},
            {"id": "T5", "title": "Run tests", "description": "Run npx playwright test.",
             "kind": "run_tests", "depends_on": ["T3", "T4"], "acceptance": "All tests pass."},
        ],
    })


def sample_file_change() -> FileChange:
    return FileChange(
        path="src/main.ts",
        operation="create",
        content="import * as Phaser from 'phaser';\n",
        reason="T3: Vite entry point",
    )


def sample_file_change_set() -> FileChangeSet:
    return FileChangeSet(changes=[sample_file_change()])


def sample_command_result() -> CommandResult:
    return CommandResult(
        command="npm run build",
        cwd="generated/block-dodger",
        exit_code=0,
        stdout="vite build\n✓ built in 812ms\n",
        duration_s=2.4,
    )


def sample_test_result() -> TestResult:
    return TestResult(
        status="passed",
        command_results=[sample_command_result()],
        summary="build ok",
    )


def sample_review_result() -> ReviewResult:
    return ReviewResult.model_validate({
        "verdict": "approve",
        "checks": [
            {"name": "scope_small", "passed": True},
            {"name": "test_hooks_present", "passed": True},
            {"name": "files_organized", "passed": True, "note": "scenes in src/scenes"},
        ],
        "issues": [],
        "suggestions": ["Add a pause key"],
        "summary": "Small, testable arcade game.",
    })


def sample_loop_history() -> list[LoopStep]:
    return [
        LoopStep(step="test", attempt=0, status="failed", summary="install ok · build failed (exit 1)"),
        LoopStep(step="fix", attempt=1, status="proposed", summary="use `import * as Phaser`",
                 files=["src/scenes/StartScene.ts"]),
        LoopStep(step="apply_fix", attempt=1, status="applied", files=["src/scenes/StartScene.ts"]),
        LoopStep(step="test", attempt=1, status="passed", summary="install ok · build ok · tests 3/3 passed"),
    ]


def sample_human_decision() -> HumanDecision:
    return HumanDecision(decision="needs_changes", note="Blocks fall too fast at the start.",
                         decided_at="2026-10-12T10:00:00+00:00")


def sample_state() -> GameFactoryState:
    return GameFactoryState(
        user_idea=BLOCK_DODGER_IDEA,
        game_spec=sample_game_spec(),
        task_plan=sample_task_plan(),
        changed_files=["src/main.ts"],
        command_results=[sample_command_result()],
        test_result=sample_test_result(),
        review_result=sample_review_result(),
        fix_attempts=1,
        loop_history=sample_loop_history(),
        status=FactoryStatus.NEEDS_HUMAN_REVIEW,
    )


ALL_SAMPLES = {
    "GameIdea": sample_game_idea,
    "GameSpec": sample_game_spec,
    "TaskPlan": sample_task_plan,
    "TaskPlan (template)": sample_template_task_plan,
    "FileChange": sample_file_change,
    "FileChangeSet": sample_file_change_set,
    "CommandResult": sample_command_result,
    "TestResult": sample_test_result,
    "ReviewResult": sample_review_result,
    "HumanDecision": sample_human_decision,
    "GameFactoryState": sample_state,
}
