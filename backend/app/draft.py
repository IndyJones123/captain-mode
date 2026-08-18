"""Captain's Mode draft state machine (latest rules, post-7.36).

Pick order per side:
  first-pick side  : 3 ban, 1 pick, 2 ban, 3 pick, 2 ban, 1 pick
  second-pick side : 4 ban, 1 pick, 1 ban, 3 pick, 2 ban, 1 pick

Total per team: 7 bans + 5 picks. 24 picks+bans total.
"""

# Turn list: (phase, team). team 0 = first-pick side, team 1 = second-pick side.
# Runs of the SAME team are contiguous blocks (e.g. "3 ban" = 3 consecutive ban turns
# for the same side), matching the latest Captain's Mode rules:
#   first-pick side : 3 ban, 1 pick, 2 ban, 3 pick, 2 ban, 1 pick
#   second-pick side: 4 ban, 1 pick, 1 ban, 3 pick, 2 ban, 1 pick
TURNS: list[tuple[str, int]] = [
    # Fase 1 Ban — team 1 (4) lalu team 0 (3)
    ("ban", 1), ("ban", 1), ("ban", 1), ("ban", 1),
    ("ban", 0), ("ban", 0), ("ban", 0),
    # Fase 2 Pick — 1-1
    ("pick", 0), ("pick", 1),
    # Fase 3 Ban — team 0 (2) lalu team 1 (1)
    ("ban", 0), ("ban", 0), ("ban", 1),
    # Fase 4 Pick — 3-3
    ("pick", 1), ("pick", 1), ("pick", 1),
    ("pick", 0), ("pick", 0), ("pick", 0),
    # Fase 5 Ban — team 0 (2) lalu team 1 (2)
    ("ban", 0), ("ban", 0), ("ban", 1), ("ban", 1),
    # Fase 6 Pick — 1-1
    ("pick", 1), ("pick", 0),
]

TURN_MS = 30_000          # per-turn timer, auto-pick random on expiry
MAX_PICKS = 5
MAX_BANS = 7

PHASE_LABELS = {
    "ban": "Ban Phase",
    "pick": "Pick Phase",
}


def picks_for(team: int, picks_count: int) -> str:
    """Human label for the pick batch: 'Pick 1' or 'Pick 2-4'."""
    # not used by the engine; kept for clarity in logs
    return f"Pick {picks_count}"


def draft_turn_blocks() -> list[dict]:
    """Collapse TURNS into contiguous blocks for the UI timeline.

    Each block: {"phase": "ban"|"pick", "team": 0|1, "count": n, "start": step, "end": step}
    Team 0 = first-pick side (Radiant), team 1 = second-pick side (Dire).
    """
    blocks: list[dict] = []
    for i, (phase, team) in enumerate(TURNS):
        if blocks and blocks[-1]["phase"] == phase and blocks[-1]["team"] == team:
            blocks[-1]["count"] += 1
            blocks[-1]["end"] = i
        else:
            blocks.append({"phase": phase, "team": team, "count": 1, "start": i, "end": i})
    return blocks


class DraftState:
    """Pure state machine. No I/O, no time — engine drives it."""

    def __init__(self) -> None:
        self.step = 0                 # index into TURNS
        self.bans = [[], []]          # bans[team] -> list[hero_id]
        self.picks = [[], []]         # picks[team] -> list[hero_id]
        self.phase = TURNS[0][0]
        self.current_team = TURNS[0][1]
        self.started = False
        self.finished = False

    @property
    def turn_phase(self) -> str:
        return self.phase

    @property
    def turn_team(self) -> int:
        return self.current_team

    def remaining_actions(self, team: int, phase: str) -> int:
        """Actions still due for team in this phase across the whole draft."""
        return sum(1 for p, t in TURNS[self.step:] if p == phase and t == team)

    def start(self) -> None:
        self.started = True
        self.step = 0
        self.phase, self.current_team = TURNS[0]
        # note: do NOT advance here — step 0 is the first real action

    def apply(self, team: int, action: str, hero_id: int) -> str:
        """Return 'ok', or error string."""
        if self.finished:
            return "draft already finished"
        if not self.started:
            return "draft not started"
        if self.phase != action:
            return f"wrong phase: expected {self.phase}, got {action}"
        if self.current_team != team:
            return "not your turn"
        bucket = self.bans if action == "ban" else self.picks
        if hero_id in bucket[0] or hero_id in bucket[1]:
            return "hero already picked/banned"
        if action == "pick" and len(bucket[team]) >= MAX_PICKS:
            return "picks exhausted"
        if action == "ban" and len(bucket[team]) >= MAX_BANS:
            return "bans exhausted"
        bucket[team].append(hero_id)
        self._advance()
        return "ok"

    def _advance(self) -> None:
        """Advance step past the just-consumed action, skipping exhausted teams.

        In the base CM order each team's ban slots are contiguous, so skipping
        is only needed if a team somehow exhausts its quota mid-sequence.
        """
        self.step += 1
        if self.step >= len(TURNS):
            self.finished = True
            self.phase = "done"
            return
        # skip turns for a team that already has all 5 picks (defensive)
        while self.step < len(TURNS):
            p, t = TURNS[self.step]
            if p == "pick" and len(self.picks[t]) >= MAX_PICKS:
                self.step += 1
                continue
            break
        if self.step >= len(TURNS):
            self.finished = True
            self.phase = "done"
            return
        self.phase, self.current_team = TURNS[self.step]
