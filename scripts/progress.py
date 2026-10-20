"""The progress bar participant commands print while they wait."""

WIDTH = 20


def bar(done: int, total: int) -> str:
    """Render finished steps as a bar and a percentage, such as `[██████████░░░░░░░░░░]  50%`.

    The share counts steps actually finished, never elapsed time, so it cannot
    promise a finish nobody knows.
    """
    share = done / total if total else 1.0
    filled = round(WIDTH * share)
    return f"[{'█' * filled}{'░' * (WIDTH - filled)}] {round(100 * share):3d}%"
