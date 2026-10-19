"""External retopology engines.

Engine modules register themselves here via ``@register_engine``
(see ``base.py``); the UI and operators look engines up in that
registry, so it must be populated before any panel/operator runs.
"""

# Importing the engine modules fires their @register_engine decorators.
from . import autoremesher_engine  # noqa: F401  (registers AutoRemesherEngine)
