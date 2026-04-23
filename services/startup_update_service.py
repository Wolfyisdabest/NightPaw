from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = ROOT / "data" / "startup_snapshot.json"
WATCH_DIRS = [ROOT / "cogs", ROOT / "services"]
WATCH_FILES = [ROOT / "main.py", ROOT / "config.py", ROOT / "checks.py"]

IMPACT_HINTS: dict[str, str] = {
    "cogs/ai.py": "AI routing/commands touched",
    "services/ai_service.py": "AI response logic/fallbacks touched",
    "services/runtime_intelligence.py": "runtime context/identity logic touched",
    "services/ai_state.py": "memory/history/settings touched",
    "services/feature_intelligence.py": "command awareness/help grouping touched",
    "services/trust_service.py": "trusted-user/pack access touched",
    "services/startup_update_service.py": "startup reporting touched",
    "main.py": "startup/reboot/runtime logging touched",
    "config.py": "configuration/runtime settings touched",
    "checks.py": "permission/access checks touched",
}

IMPACT_PREFIX_HINTS: dict[str, str] = {
    "cogs/": "command/cog path touched",
    "services/": "internal service path touched",
}

AI_IMPACT_PATHS = {
    "cogs/ai.py",
    "services/ai_service.py",
    "services/runtime_intelligence.py",
    "services/ai_state.py",
    "services/feature_intelligence.py",
}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def build_snapshot() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in WATCH_FILES:
        if path.exists():
            result[path.relative_to(ROOT).as_posix()] = _file_hash(path)
    for folder in WATCH_DIRS:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            result[path.relative_to(ROOT).as_posix()] = _file_hash(path)
    return result


def _impact_lines(paths: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    ai_related = False

    for path in paths:
        if path in AI_IMPACT_PATHS:
            ai_related = True
        impact = IMPACT_HINTS.get(path)
        if impact is None:
            for prefix, fallback in IMPACT_PREFIX_HINTS.items():
                if path.startswith(prefix):
                    impact = fallback
                    break
        if impact is None or impact in seen:
            continue
        seen.add(impact)
        lines.append(f"- {impact}")
        if len(lines) >= 4:
            break

    if ai_related and len(lines) < 4:
        recommendation = "- Recommended: run `!aidiag` after the first AI interaction"
        if recommendation not in seen:
            lines.append(recommendation)
    return lines


def compare_and_store_snapshot() -> str | None:
    current = build_snapshot()
    previous: dict[str, str] = {}
    if SNAPSHOT_PATH.exists():
        try:
            previous = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    added = sorted(k for k in current if k not in previous)
    removed = sorted(k for k in previous if k not in current)
    changed = sorted(k for k in current if k in previous and current[k] != previous[k])

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")

    if not previous:
        return "🆕 Startup snapshot created. No earlier snapshot existed yet."
    if not (added or removed or changed):
        return None

    total_changes = len(added) + len(removed) + len(changed)
    lines = [f"🛠️ NightPaw startup update report: {total_changes} file change(s) detected."]
    if added:
        lines.append("Added:")
        lines.extend(f"+ {item}" for item in added[:20])
    if changed:
        lines.append("Changed:")
        lines.extend(f"~ {item}" for item in changed[:20])
    if removed:
        lines.append("Removed:")
        lines.extend(f"- {item}" for item in removed[:20])
    shown = min(len(added), 20) + min(len(changed), 20) + min(len(removed), 20)
    extra = max(0, total_changes - shown)
    if extra:
        lines.append(f"...and {extra} more file changes.")
    impact = _impact_lines(added + changed + removed)
    if impact:
        lines.append("Impact:")
        lines.extend(impact)
    return "\n".join(lines)
