import time
from typing import Dict, List, Set, Tuple

banned_users: Set[int] = set()

# user_id -> set of used admin commands
admin_usage_log: Dict[int, Set[str]] = {}
# user_id -> total count of admin command calls
admin_usage_count: Dict[int, int] = {}
# chronological list of (timestamp, user_id, command)
admin_action_history: List[Tuple[int, int, str]] = []

# user_id -> last activity timestamp
online_users: Dict[int, float] = {}


def record_admin_usage(user_id: int, command: str) -> None:
    """Record usage of an admin command."""
    admin_usage_log.setdefault(user_id, set()).add(command)
    admin_usage_count[user_id] = admin_usage_count.get(user_id, 0) + 1
    admin_action_history.append((int(time.time()), user_id, command))
