"""Portable attempt state shared by practice and timed exam workspaces."""
from dataclasses import dataclass, field


@dataclass
class ExamSessionState:
    mode: str = "exam"
    elapsed_seconds: int = 0
    active_question: str = ""
    flagged_questions: set[str] = field(default_factory=set)
    assisted: bool = False
    pause_count: int = 0
    completed: bool = False

    @classmethod
    def restore(cls, snapshot, mode="exam"):
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        raw = snapshot.get("workspace", {})
        raw = raw if isinstance(raw, dict) else {}
        try:
            elapsed = max(0, int(raw.get("elapsed_seconds", 0)))
            pauses = max(0, int(raw.get("pause_count", 0)))
        except (TypeError, ValueError):
            elapsed = pauses = 0
        flags = raw.get("flagged_questions", [])
        return cls(
            mode="practice" if raw.get("mode", mode) == "practice" else "exam",
            elapsed_seconds=elapsed, pause_count=pauses,
            active_question=str(raw.get("active_question", "")),
            flagged_questions={str(q) for q in flags} if isinstance(flags, list) else set(),
            assisted=bool(raw.get("assisted", False)), completed=bool(raw.get("completed", False)),
        )

    def snapshot(self):
        return dict(mode=self.mode, elapsed_seconds=self.elapsed_seconds,
                    active_question=self.active_question, flagged_questions=sorted(self.flagged_questions),
                    assisted=self.assisted, pause_count=self.pause_count, completed=self.completed)
