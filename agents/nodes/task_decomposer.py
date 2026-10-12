"""Task decomposer node (M5): GameSpec -> validated, ordered TaskPlan.

Only plans; never writes files. Schema validation (unique ids, dependencies only on
earlier tasks) comes from TaskPlan; `check_plan` adds semantic rules whose errors are
fed into the single repair attempt. Reference: docs/NODES.md.
"""

from agents.generators.phaser_template import guide, locked_files
from agents.llm import invoke_structured, make_llm
from agents.prompts import render_prompt
from agents.schemas import FactoryStatus, GameFactoryState, GameSpec, NodeError, TaskPlan

NODE = "task_decomposer"

MIN_TASKS, MAX_TASKS = 5, 12
REQUIRED_KINDS = ("config", "code", "test_hooks", "tests", "build", "run_tests")
TEMPLATE_REQUIRED_KINDS = ("code", "test_hooks", "tests", "build", "run_tests")  # package.json comes from the template
AFTER_CODE_KINDS = ("build", "run_tests")


def check_plan(plan: TaskPlan, spec: GameSpec, template: str | None = None) -> list[str]:
    """Semantic rules beyond the schema. Returns error strings (empty = ok).

    With a template (M19) no `config` task is required and its locked files may not be targets.
    """
    errors = []
    required = TEMPLATE_REQUIRED_KINDS if template else REQUIRED_KINDS
    if plan.game_slug != spec.slug:
        errors.append(f"game_slug: must be '{spec.slug}' (the GameSpec slug), got '{plan.game_slug}'")
    if not MIN_TASKS <= len(plan.tasks) <= MAX_TASKS:
        errors.append(f"tasks: need {MIN_TASKS} to {MAX_TASKS} tasks, got {len(plan.tasks)}")
    kinds = [t.kind for t in plan.tasks]
    missing = [k for k in required if k not in kinds]
    if missing:
        errors.append(f"tasks: missing task kinds {missing}; every plan needs {list(required)}")
    locked = locked_files(template)
    for task in plan.tasks:
        for path in task.target_files:
            if path in locked:
                errors.append(f"{task.id}: '{path}' is a locked template file; remove it from target_files "
                              f"(locked: {list(locked)})")
    if "code" in kinds:
        last_code = max(i for i, k in enumerate(kinds) if k == "code")
        for i, task in enumerate(plan.tasks):
            if task.kind in AFTER_CODE_KINDS and i < last_code:
                errors.append(f"tasks: {task.id} ({task.kind}) must come after all 'code' tasks")
    return errors


def decompose(spec: GameSpec, llm=None, template: str | None = None) -> TaskPlan | NodeError:
    schema = TaskPlan.model_json_schema()
    prompt = render_prompt("task_decomposer", game_spec=spec, project_base=guide(template), schema=schema)
    return invoke_structured(llm or make_llm(), NODE, prompt, TaskPlan, schema,
                             check=lambda plan: check_plan(plan, spec, template))


def task_decomposer_node(state: GameFactoryState, llm=None) -> dict:
    """LangGraph node: returns a partial state update."""
    if state.game_spec is None:
        error = NodeError(node=NODE, message="state has no game_spec; run the planner first")
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {error.model_dump_json()}"}
    result = decompose(state.game_spec, llm=llm, template=state.template)
    if isinstance(result, NodeError):
        return {"status": FactoryStatus.ERROR, "error": f"{NODE}: {result.model_dump_json()}"}
    return {"task_plan": result, "status": FactoryStatus.TASKS_PLANNED, "error": None}
