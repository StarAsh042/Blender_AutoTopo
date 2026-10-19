"""Engine abstraction for AutoTopo remesh backends.

Every remeshing backend (QuadWild, QuadriFlow, AutoRemesher, ...) is a
:class:`RemeshEngine` subclass registered through :func:`register_engine`.
The UI and operators never branch on an engine id — they look the engine
up in the registry and use its :attr:`settings` to drive the panel.

Design rules:

* **Engines own their parameters.** Each engine declares the settings it
  understands (name, kind, recommended default, range, description) via
  :class:`SettingSpec`. The panel draws whatever the engine declares, so
  adding an engine needs no changes to ``ui/panels.py``.
* **Defaults are the algorithm's recommended values**, not arbitrary
  numbers. Every spec records ``source`` so a user can tell where a
  default came from.
* **Availability is an engine concern.** :meth:`is_available` reports
  whether the backend can run right now (native library present, external
  executable found, ...). The panel shows a hint when it cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from .evaluation import RetopoResult

# Sentinel returned when a settings dict has no entry for a key.
_MISSING = object()


@dataclass
class SettingSpec:
    """Declaration of a single user-facing engine parameter.

    Attributes:
        key: Name of the ``AutoTopoProperties`` property backing this
            setting. Property names are shared across engines, so the
            same key may be reused by several engines.
        label: Chinese label shown in the panel.
        kind: One of ``'int'``, ``'float'``, ``'bool'``.
        default: Recommended value. Used as the Blender property default
            and as the fallback when a key is missing from the settings
            dict passed to :meth:`RemeshEngine.run`.
        description: Tooltip text.
        source: Where ``default`` came from, e.g. ``"QuadWild 论文"``.
        min / max / soft_min / soft_max: Numeric bounds (int / float).
        precision: Decimal places for float controls.
        unit: Optional unit string appended to the label, e.g. ``"°"``.
        advanced: When True the setting is drawn in the collapsed
            ``高级`` section instead of the main body.
        show_if: Optional predicate ``(settings) -> bool``; the setting is
            only drawn when it returns True.
    """

    key: str
    label: str
    kind: str
    default: Any
    description: str = ""
    source: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    soft_min: Optional[float] = None
    soft_max: Optional[float] = None
    precision: int = 2
    unit: str = ""
    advanced: bool = False
    show_if: Optional[Callable[[Dict[str, Any]], bool]] = None

    @property
    def display_label(self) -> str:
        return f"{self.label} ({self.unit})" if self.unit else self.label


class RemeshEngine:
    """Base class for a remeshing backend.

    Subclasses must set :attr:`id`, :attr:`label`, :attr:`description`
    and :attr:`settings`, and implement :meth:`is_available` and
    :meth:`run`.
    """

    id: str = ""
    label: str = ""
    description: str = ""
    settings: Sequence[SettingSpec] = ()
    # Shared property keys declared on ``AutoTopoProperties`` but not owned
    # by this engine, that this engine wants shown in the panel (e.g.
    # ``("sharp_angle_threshold",)``). The panel draws them in a generic
    # "特征保留" box; engines that don't use them leave this empty.
    shared_props: tuple = ()

    # ------------------------------------------------------------------
    # capability
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """True when this backend can run in the current environment."""
        raise NotImplementedError

    @staticmethod
    def unavailable_hint() -> str:
        """Human-readable reason shown in the panel when unavailable."""
        return ""

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    @staticmethod
    def run(
        input_mesh: Any,
        target_face_count: int,
        settings: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> RetopoResult:
        """Run the backend. Safe to call from a background thread.

        Args:
            input_mesh: ``MeshData`` with the triangulated source mesh
                (and sharp-edge set when the backend supports features).
            target_face_count: Desired output face budget.
            settings: Mapping of :attr:`SettingSpec.key` -> value. Missing
                keys fall back to the spec ``default``.
            progress_callback: ``(step_name, percent)`` reporter.
            cancel_check: Returns True when the user cancelled.

        Returns:
            A :class:`RetopoResult`. Implementations must never raise:
            failures go into ``result.error_message``.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls, key: str, settings: Optional[Dict[str, Any]]
    ) -> Any:
        """Value for ``key``: from ``settings``, else the spec default."""
        if settings is not None:
            value = settings.get(key, _MISSING)
            if value is not _MISSING:
                return value
        for spec in cls.settings:
            if spec.key == key:
                return spec.default
        return None

    @classmethod
    def resolved_settings(
        cls, settings: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Full mapping of every declared setting to its effective value."""
        return {spec.key: cls.resolve(spec.key, settings)
                for spec in cls.settings}


# ----------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------

_REGISTRY: Dict[str, type] = {}
_ORDER: List[str] = []


def register_engine(engine_cls: type) -> type:
    """Register an engine class. Meant to be used as a decorator."""
    engine_id = getattr(engine_cls, "id", "")
    if not engine_id:
        raise ValueError(f"engine class {engine_cls!r} has no id")
    _REGISTRY[engine_id] = engine_cls
    if engine_id not in _ORDER:
        _ORDER.append(engine_id)
    return engine_cls


def get_engine(engine_id: str) -> Optional[type]:
    """Look up a registered engine by id (``None`` when unknown)."""
    return _REGISTRY.get(engine_id)


def list_engines() -> List[type]:
    """All registered engines, in registration order."""
    return [_REGISTRY[i] for i in _ORDER]


def engine_items() -> List[tuple]:
    """``(id, label, description)`` triples for ``EnumProperty``."""
    return [(e.id, e.label, e.description) for e in list_engines()]


def all_setting_specs() -> List[SettingSpec]:
    """Every setting declared by any engine, de-duplicated by key.

    Used by ``ui/properties.py`` to know which Blender properties must
    exist.
    """
    out: Dict[str, SettingSpec] = {}
    for engine in list_engines():
        for spec in engine.settings:
            out.setdefault(spec.key, spec)
    return list(out.values())
