"""External retopology engines (QuadWild / AutoRemesher / QuadriFlow).

Importing this package triggers the ``@register_engine`` decorators on the
engine modules, populating the engine registry (see ``base.py``). The UI
and operators look engines up there, so the registry must be populated
before any panel/operator runs.
"""

# Importing the engine modules fires their @register_engine decorators.
from . import autoremesher_engine  # noqa: F401  (registers AutoRemesherEngine)
from . import quadriflow_engine    # noqa: F401  (registers QuadriFlowEngine)
from . import quadwild_engine      # noqa: F401  (registers QuadWildEngine)
