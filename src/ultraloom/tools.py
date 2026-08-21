"""Tool profiles: the ceiling on what an AgentNode can reach.

Reading is the default. Writing and shell access have to be asked for, so a
node that should only interpret a report cannot touch a source file — because
the tool is absent, not because the node is well behaved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

_READ = ("Glob", "Grep", "Read")

# Every profile is stored sorted and duplicate-free: the tool list becomes part
# of a prompt cache prefix and of a journal entry, so set iteration order must
# never leak into it.
# A proxy and not a plain dict: with permission_mode="dontAsk" these profiles
# are the only thing between an agent node and Bash or Write. A runtime write --
# a flow module, a plugin, a test that forgets to restore -- would widen that
# ceiling for the whole process silently, and the journal records the profile
# *name*, not the resolved list, so nothing would show it afterwards.
PROFILES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "read_only": _READ,
        "edit": tuple(sorted({*_READ, "Edit", "Write"})),
        "shell": tuple(sorted({*_READ, "Bash"})),
        "mcp": _READ,
    }
)

_TAKES_SERVERS = frozenset({"mcp"})


class UnknownProfileError(ValueError):
    """Raised for a profile name that is not defined."""


def resolve_tools(profile: str, mcp_servers: Sequence[str] = ()) -> tuple[str, ...]:
    """The tools a node with this profile may use."""
    try:
        base = PROFILES[profile]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise UnknownProfileError(f"unknown tool profile {profile!r}; known: {known}") from None
    if profile not in _TAKES_SERVERS:
        return base
    return tuple(sorted({*base, *(f"mcp__{server}" for server in mcp_servers)}))
