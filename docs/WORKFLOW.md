# Milestone workflow

## Loop (one milestone at a time)

1. **Read** CLAUDE.md → ROADMAP entry → plan.md section for the milestone.
2. **Plan** only that milestone. Render it as a Lavish HTML page with an Approve button; wait for approval.
3. **Implement** in small steps, following [SAFETY.md](SAFETY.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
4. **Test** — add tests, run the full suite and the milestone's "Done when" command ([TESTING.md](TESTING.md)).
5. **Record** results in `docs/milestones/Mxx-<name>.md` (scope, done criteria, real command output summary, issues).
6. **Update** ROADMAP status table and the "Current status" block in CLAUDE.md; add new docs to the CLAUDE.md index.
7. **Report** to the user (template below).
8. **STOP.** Do not start the next milestone until the user explicitly says so.

## Report template

```
## Milestone N — <name>: <complete | incomplete>
### File tree        (relevant part)
### Changed files    (git status / git diff --stat)
### Commands run     (command → result summary)
### Tests            (suite result, counts)
### Issues / notes
### Next             Milestone N+1 — waiting for your permission
```

## Milestone doc template (`docs/milestones/Mxx-<name>.md`)

```
# Mxx — <name>
Status: in progress | complete
## Scope
## Done criteria
## Changes
## Verification log
## Issues / follow-ups
```
