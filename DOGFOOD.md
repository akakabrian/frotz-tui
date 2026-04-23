# DOGFOOD — frotz-tui

_Session: 2026-04-23T12:30:38, driver: pty, duration: 3.0 min_

**PASS** — ran for 2.0m, captured 28 snap(s), 1 milestone(s), 0 blocker(s), 0 major(s).

## Summary

Ran a rule-based exploratory session via `pty` driver. Found 2 UX note(s). Game reached 158 unique state snapshots. Captured 1 milestone shot(s); top candidates promoted to `screenshots/candidates/`.

## Findings

### Blockers

_None._

### Majors

_None._

### Minors

_None._

### Nits

_None._

### UX (feel-better-ifs)
- **[U1] score never changes during normal play**
  - All 117 score samples read '36'. Either scoring requires specific triggers or it's not wired to state().
- **[U2] Score never changed in state() during session**
  - Consider exposing score in /state or App attributes so agent-driven QA can verify progress.

## Coverage

- Driver backend: `pty`
- Keys pressed: 967 (unique: 58)
- State samples: 176 (unique: 158)
- Score samples: 176
- Milestones captured: 1
- Phase durations (s): A=81.5, B=21.9, C=18.1
- Snapshots: `/home/brian/AI/projects/tui-dogfood/reports/snaps/frotz-tui-20260423-122835`

Unique keys exercised: +, ,, -, ., /, 0, 1, 2, 3, 4, 5, :, ;, =, ?, H, R, [, ], a, b, backspace, c, ctrl+l, d, delete, down, end, enter, escape, f1, f2, h, home, j, k, l, left, m, n ...

## Milestones

| Event | t (s) | Interest | File | Note |
|---|---|---|---|---|
| first_input | 0.3 | 0.0 | `frotz-tui-20260423-122835/milestones/first_input.txt` | key=right |
