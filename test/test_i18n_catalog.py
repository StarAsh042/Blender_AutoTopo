"""Catalog parity checks (pure Python, no Blender required).

Enforces:
1. Every user-visible English msgid used by the addon exists in the
   zh_CN catalog (I18N-3: default language complete).
2. The catalog contains no stale entries the code never uses.
3. Every msgid and its translation use the same placeholder names
   (I18N-2).
4. Negative check: dropping a key makes the parity check fail (I18N-6,
   automated half; the catalog on disk is not modified).

Run: pytest -q test/test_i18n_catalog.py
"""
import ast
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _pkgload  # noqa: E402

_PROJECT_ROOT = os.path.dirname(_HERE)
_CATALOG = _pkgload.load_module("ui/i18n_catalog.py")

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}")

# Keyword arguments whose string values are user-visible.
_FIELD_KWARGS = {"name", "description", "bl_label", "bl_description", "text"}

# Assignment targets that hold user-visible strings.
_ASSIGN_TARGETS = {"bl_label", "bl_description", "bl_category", "status_message"}

# Calls whose first argument is a user-visible msgid.
_T_CALLS = {"t", "pgettext", "pgettext_iface"}

# Tests that exercise runtime strings (their t() literals are part of the
# contract too).
_EXTRA_TEST_FILES = (
    "test_i18n_runtime.py",
    "test_addon_integration.py",
    "test_cancel_and_errors.py",
)


def _module_files():
    files = [os.path.join(_PROJECT_ROOT, "__init__.py")]
    for sub in ("ui", "engines"):
        base = os.path.join(_PROJECT_ROOT, sub)
        for name in sorted(os.listdir(base)):
            if name.endswith(".py"):
                files.append(os.path.join(base, name))
    for name in _EXTRA_TEST_FILES:
        files.append(os.path.join(_HERE, name))
    return files


def _is_setting_spec(node):
    """SettingSpec label/description are internal metadata, not UI text."""
    return isinstance(node.func, ast.Name) and node.func.id == "SettingSpec"


def extract_msgids(path):
    """Extract user-visible string literals from one Python file."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)

    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_setting_spec(node):
                continue
            func = node.func
            fname = getattr(func, "id", None) or getattr(func, "attr", None)
            if fname in _T_CALLS and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
            # Local progress helper: report("Exporting mesh...", pct)
            if fname == "report" and not isinstance(func, ast.Attribute) and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
            for kw in node.keywords:
                if kw.arg in _FIELD_KWARGS and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str) and kw.value.value:
                        found.add(kw.value.value)
                # EnumProperty(items=[(id, label, description), ...])
                if kw.arg == "items" and isinstance(kw.value, ast.List):
                    for elt in kw.value.elts:
                        if not isinstance(elt, ast.Tuple):
                            continue
                        for item in elt.elts[1:]:
                            if isinstance(item, ast.Constant) \
                                    and isinstance(item.value, str) \
                                    and item.value:
                                found.add(item.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                name = getattr(target, "id", None) or getattr(target, "attr", None)
                if name in _ASSIGN_TARGETS:
                    if isinstance(node.value, ast.Constant) \
                            and isinstance(node.value.value, str) \
                            and node.value.value:
                        found.add(node.value.value)
        # Engine availability hints are returned from a known function and
        # displayed through t() in the panel.
        elif isinstance(node, ast.FunctionDef) and node.name == "unavailable_hint":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant):
                    if isinstance(sub.value.value, str) and sub.value.value:
                        found.add(sub.value.value)
    return found


def used_msgids():
    found = set()
    for path in _module_files():
        found |= extract_msgids(path)
    return found


def placeholders(text):
    return set(_PLACEHOLDER.findall(text))


def check_parity(catalog):
    used = used_msgids()
    known = set(catalog)
    missing = used - known
    stale = known - used
    bad_placeholders = []
    for msgid in used & known:
        if placeholders(msgid) != placeholders(catalog[msgid]):
            bad_placeholders.append((msgid, catalog[msgid]))
    return missing, stale, bad_placeholders


def test_default_language_is_complete():
    missing, _, _ = check_parity(_CATALOG._ENTRIES)
    assert not missing, f"msgids missing from zh_CN catalog: {sorted(missing)}"


def test_catalog_has_no_stale_entries():
    _, stale, _ = check_parity(_CATALOG._ENTRIES)
    assert not stale, f"catalog entries not used by code: {sorted(stale)}"


def test_placeholder_parity():
    _, _, bad = check_parity(_CATALOG._ENTRIES)
    assert not bad, f"placeholder mismatch: {bad}"


def test_negative_missing_key_is_detected():
    # Drop one key and confirm the parity check reports it. This is the
    # automated half of I18N-6; the catalog on disk is not modified.
    catalog = dict(_CATALOG._ENTRIES)
    victim = next(iter(catalog))
    del catalog[victim]
    missing, _, _ = check_parity(catalog)
    assert victim in missing


def test_translations_register_ui_contexts():
    """Blender draws RNA properties and operator buttons in dedicated
    contexts; registering only '*' and 'AutoTopo' leaves those strings
    untranslated (issue #7)."""
    required = {
        ("*", "Target Face Count"),
        ("AutoTopo", "Target Face Count"),
        ("Operator", "Retopologize"),
        ("RNA", "Target Face Count"),
        ("RNA", "Adaptive Density"),
    }
    for locale in ("zh_HANS", "zh_CN"):
        catalog = _CATALOG.TRANSLATIONS[locale]
        missing = sorted(key for key in required if key not in catalog)
        assert not missing, "%s missing UI-context keys: %s" % (locale, missing)


def test_retopologize_button_uses_explicit_translation():
    """The two Run buttons must pass text=t("Retopologize").

    Operator buttons that omit text= rely on Blender auto-translating
    bl_label. That path is unreliable on 3.x, leaving the button in
    English (issue #7). Every other button already passes text=t(...).
    """
    panels = os.path.join(_PROJECT_ROOT, "ui", "panels.py")
    with open(panels, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=panels)

    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(
            isinstance(a, ast.Constant) and a.value == "autotopo.retopologize"
            for a in node.args
        )
    ]
    assert calls, "no autotopo.retopologize operator call found in panels.py"
    for node in calls:
        text_kw = next((kw for kw in node.keywords if kw.arg == "text"), None)
        assert text_kw is not None, (
            "retopologize operator at line %d missing explicit text=" % node.lineno
        )
        value = text_kw.value
        is_translated = (
            isinstance(value, ast.Call)
            and getattr(value.func, "id", None) == "t"
            and value.args
            and isinstance(value.args[0], ast.Constant)
            and value.args[0].value == "Retopologize"
        )
        assert is_translated, (
            "retopologize operator at line %d must use text=t(\"Retopologize\")"
            % node.lineno
        )


def test_translations_register_both_locale_keys():
    """Blender 3.x uses zh_CN; 4.0+ uses zh_HANS.

    Both locales must be registered or the whole catalog is silently
    ignored on the other major version. Guard the registration surface
    itself, which test_i18n_runtime.py cannot reach without Blender.
    """
    translations = _CATALOG.TRANSLATIONS
    expected = {
        (context, msgid): text
        for context in ("*", "AutoTopo", "Operator", "RNA")
        for msgid, text in _CATALOG._ENTRIES.items()
    }
    for locale in ("zh_CN", "zh_HANS"):
        assert locale in translations, f"missing locale key: {locale}"
        assert translations[locale] == expected, f"catalog mismatch for {locale}"
