"""Translation registration and runtime helpers for AutoTopo.

Static UI strings (``name=`` / ``description=`` / ``bl_label=``) are
translated by Blender itself: the catalog is keyed by the source string
and Blender looks it up while drawing. Strings produced at runtime
(operator reports, status lines, result summaries) are not translated
automatically and must go through :func:`t`.

The registration helpers are idempotent: enabling, disabling and
re-enabling the addon in one session must not leave a stale translation
module behind.
"""

import bpy

from .i18n_catalog import TRANSLATIONS

# Private translation context for runtime strings. The ``"*"`` context is
# checked against Blender's built-in catalog first, so runtime strings
# must not rely on it.
_CONTEXT = "AutoTopo"

_registered = False


def register_translations(module_name: str) -> None:
    """Register the catalog, replacing a stale registration if present."""
    global _registered
    if _registered:
        bpy.app.translations.unregister(module_name)
        _registered = False
    bpy.app.translations.register(module_name, TRANSLATIONS)
    _registered = True


def unregister_translations(module_name: str) -> None:
    """Remove the catalog; safe to call when nothing is registered."""
    global _registered
    if not _registered:
        return
    bpy.app.translations.unregister(module_name)
    _registered = False


def t(msgid: str, **kwargs) -> str:
    """Translate a runtime string and fill ``{placeholders}``.

    Call from the main thread only (UI drawing, operator reports,
    completion callbacks). Missing placeholders raise ``KeyError`` on
    purpose: silently leaving ``{name}`` in the UI is a bug.
    """
    text = bpy.app.translations.pgettext_iface(msgid, _CONTEXT)
    if kwargs:
        return text.format(**kwargs)
    return text
