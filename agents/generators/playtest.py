"""Playtest plan of a game (M21c): how the acceptance test plays THIS game, derived from its GameSpec.

The planner writes `GameSpec.playtest` (generic checks: avatar, inputs and what they cause, things that
move on their own, HUD, difficulty, how a round ends). Code here normalizes it, checks it against the
rest of the spec, and derives what the game must expose to the tests (the hook contract). Nothing in
here knows about a particular genre.
"""

import re

from agents.schemas import GameSpec, Playtest

CLICK = "Click"
ARROWS = {"left": "ArrowLeft", "right": "ArrowRight", "up": "ArrowUp", "down": "ArrowDown"}
GLYPHS = {"←": "ArrowLeft", "→": "ArrowRight", "↑": "ArrowUp", "↓": "ArrowDown"}
NAMED = {"space": "Space", "spacebar": "Space", "enter": "Enter", "return": "Enter", "escape": "Escape",
         "esc": "Escape", "shift": "ShiftLeft", "tab": "Tab"}
POINTER = re.compile(r"click|mouse|tap|touch|pointer|cursor position", re.I)
SECONDS = re.compile(r"(\d+)\s*(?:s\b|sec|second)", re.I)
PLAYER_EXPECT = ("player_left", "player_right", "player_up", "player_down")

# Hooks every game exposes (template src/testHooks.ts); the rest depends on the playtest.
BASE_STATE = ("scene", "result", "texts", "objects")
BASE_API = ("startGame", "skipTime", "finishRound")


def normalize_key(text: str) -> str | None:
    """'Left Arrow' / '←' / 'arrowleft' -> 'ArrowLeft'; 'Mouse click' -> 'Click'; 'w' -> 'KeyW'; None if unknown."""
    raw = text.strip()
    if raw in GLYPHS:
        return GLYPHS[raw]
    if POINTER.search(raw):
        return CLICK
    low = re.sub(r"[\s_-]+", " ", raw.lower()).strip()
    compact = low.replace(" ", "")
    for side, key in ARROWS.items():
        if compact in (f"arrow{side}", f"{side}arrow", f"{side}arrowkey", f"arrow{side}key", side):
            return key
    if compact in NAMED:
        return NAMED[compact]
    letter = re.fullmatch(r"(?:key)?([a-z0-9])", compact)
    if letter:
        char = letter.group(1)
        return f"Key{char.upper()}" if char.isalpha() else f"Digit{char}"
    return None


def control_keys(spec: GameSpec) -> set[str]:
    """Normalized inputs of spec.controls (an entry like 'ArrowLeft / ArrowRight' yields both)."""
    keys = set()
    for control in spec.controls:
        for part in re.split(r"\s*(?:/|,|\bor\b|\band\b)\s*", control.input):
            if part and (key := normalize_key(part)):
                keys.add(key)
    return keys


def normalize_playtest(spec: GameSpec) -> GameSpec:
    """Canonical key names in playtest.inputs (unknown names stay as written, so check_playtest reports them)."""
    if spec.playtest is None:
        return spec
    inputs = [i.model_copy(update={"input": normalize_key(i.input) or i.input}) for i in spec.playtest.inputs]
    return spec.model_copy(update={"playtest": spec.playtest.model_copy(update={"inputs": inputs})})


def check_playtest(spec: GameSpec) -> list[str]:
    """Consistency of the playtest with the rest of the spec. Returns error strings (empty = ok)."""
    pt = spec.playtest
    if pt is None:
        return ["playtest: required — describe how a test plays this game (see the rules)"]
    errors = []
    keys = control_keys(spec)
    if len(pt.inputs) > 4:
        errors.append("playtest.inputs: at most 4 inputs")
    for i, item in enumerate(pt.inputs):
        where = f"playtest.inputs.{i}"
        key = normalize_key(item.input)
        if key is None:
            errors.append(f"{where}.input: unknown input {item.input!r}; use a key name such as 'ArrowLeft', "
                          "'ArrowUp', 'Space', 'KeyW', 'Enter', or 'Click' for the mouse")
        elif key not in keys:
            errors.append(f"{where}.input: {key!r} is not one of the game's controls {sorted(keys)}")
        if item.expect in PLAYER_EXPECT and pt.player is None:
            errors.append(f"{where}.expect: {item.expect!r} needs an avatar, but playtest.player is null")
    if pt.round_end.by == "timer":
        if pt.round_end.seconds is None:
            errors.append("playtest.round_end.seconds: required when the round ends by timer")
        else:
            stated = {int(n) for n in SECONDS.findall(f"{spec.win_condition} {spec.lose_condition}")}
            if stated and pt.round_end.seconds not in stated:
                errors.append(f"playtest.round_end.seconds: {pt.round_end.seconds} does not match the "
                              f"win/lose conditions ({sorted(stated)} seconds)")
    if pt.hud == "time" and pt.round_end.by != "timer" and not pt.difficulty_ramps and not pt.moves_on_its_own:
        errors.append("playtest.hud: 'time' needs something that changes with time (a timer, motion or "
                      "difficulty); use 'input' or 'none'")
    return errors


def derive_playtest(spec: GameSpec) -> Playtest:
    """Best-effort playtest for specs written before M21c (no planner playtest)."""
    keys = control_keys(spec)
    inputs = [{"input": key, "expect": f"player_{side}"} for side, key in ARROWS.items() if key in keys]
    if not inputs and CLICK in keys:
        inputs = [{"input": CLICK, "expect": "state_changes"}]
    if not inputs:
        inputs = [{"input": sorted(keys)[0] if keys else CLICK, "expect": "state_changes"}]
    seconds = [int(n) for n in SECONDS.findall(f"{spec.win_condition} {spec.lose_condition}")]
    timer = {"by": "timer", "seconds": seconds[0]} if seconds else {"by": "hook"}
    has_player = any(i["expect"].startswith("player_") for i in inputs)
    return Playtest.model_validate({
        "player": {"moves_by_itself": False} if has_player else None,
        "inputs": inputs, "moves_on_its_own": False, "hud": "time" if seconds else "none",
        "difficulty_ramps": False, "round_end": timer,
    })


def playtest_of(spec: GameSpec) -> Playtest:
    return spec.playtest if spec.playtest is not None else derive_playtest(spec)


def scene_members(pt: Playtest) -> dict[str, str]:
    """GameScene members the tests read through the template hooks: member -> what it must hold."""
    members = {}
    if pt.player is not None:
        members["player"] = "the avatar game object (this.player), its x/y is read by the tests"
    if any(i.expect == "score_up" for i in pt.inputs) or pt.hud == "input":
        members["score"] = "the current score / count as a number (this.score)"
    if pt.difficulty_ramps:
        members["difficulty"] = "a number that grows during a round (this.difficulty)"
    if any(i.input == CLICK for i in pt.inputs):
        members["clickTarget"] = ("where a meaningful click goes right now: {x, y} in game coordinates, or null "
                                  "(this.clickTarget, a property or a getter)")
    return members


def hook_contract(spec: GameSpec) -> tuple[str, ...]:
    """Names the test hooks must expose for this game."""
    pt = playtest_of(spec)
    return ("__GAME_STATE__", "__TEST_API__", *BASE_STATE, *scene_members(pt), *BASE_API)


def describe(spec: GameSpec) -> str:
    """Human/LLM-readable summary of what the acceptance test will do with this game."""
    pt = playtest_of(spec)
    lines = ["The automatic acceptance test (written by code, locked) plays this game like a person:",
             "- the start screen must show the title and explain the controls; a click anywhere starts the game;"]
    if pt.player is not None and not pt.player.moves_by_itself:
        lines.append("- with no input the avatar (this.player) must stay where it is;")
    for i in pt.inputs:
        how = "a real click at __GAME_STATE__.clickTarget" if i.input == CLICK else f"the real key {i.input}"
        lines.append(f"- {how} must cause: {i.expect.replace('_', ' ')};")
    if pt.moves_on_its_own:
        lines.append("- within 4 seconds of real play something must move on its own (__GAME_STATE__.objects);")
    if pt.hud == "time":
        lines.append("- the on-screen text must change after skipTime(5);")
    elif pt.hud == "input":
        lines.append("- the on-screen text must change after the inputs above (score / moves);")
    if pt.difficulty_ramps:
        lines.append("- __GAME_STATE__.difficulty must grow after skipTime(20);")
    if pt.round_end.by == "timer":
        lines.append(f"- skipTime({pt.round_end.seconds}) must end the round and show the result screen;")
    else:
        lines.append("- __TEST_API__.finishRound('lose') must show the result screen;")
    lines.append("- the result screen shows a message, and a click on it starts a new round.")
    return "\n".join(lines)
