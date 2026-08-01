"""Multi-boundary Streamlit widget registration hooks (observability only)."""

from __future__ import annotations

import inspect
import sys
import time
from types import MethodType
from typing import Any, Callable

from live_draft_streamlit_widget_metadata_diag import (
    REG_DIAG_CTX_KEY,
    SURFACE_CASE_A_CONTROL,
    SURFACE_PRODUCTION,
    _fn_identity,
    register_watch_user_key,
    registration_diag_context,
    resolve_diagnostic_surface,
    snapshot_from_widget_metadata_object,
)


def _emit(session: dict[str, Any], event: str, **kwargs: Any) -> dict[str, Any]:
    """Always delegate to canonical emitter (avoid stale import alias)."""
    from live_draft_streamlit_widget_metadata_diag import _emit as emit_fn

    return emit_fn(session, event, **kwargs)

REG_HOOK_ENTERED = "production_stage1_registration_hook_entered"
REG_HOOK_EXITED = "production_stage1_registration_hook_exited"
HOOKS_INSTALLED = "production_stage1_registration_hooks_installed"

RUNTIME_MAP_JSON = "data/p8_streamlit_registration_runtime_map.json"
RUNTIME_MAP_TXT = "data/p8_streamlit_registration_runtime_map.txt"

_HOOK_STATE_KEY = "_solo_stage1_registration_hooks_state"


def _diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        return bool(stage1_production_ledger_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def _callable_identity(fn: Any) -> dict[str, str]:
    out = {
        "callable_module": getattr(fn, "__module__", "")[:160],
        "callable_qualname": getattr(fn, "__qualname__", repr(fn))[:160],
        "callable_identity": _fn_identity(fn),
    }
    try:
        out["source_file"] = str(inspect.getsourcefile(fn) or "")[:260]
        out["source_line"] = str(inspect.getsourcelines(fn)[1])
    except Exception:
        out["source_file"] = ""
        out["source_line"] = ""
    func = getattr(fn, "__func__", fn)
    out["func_identity"] = _fn_identity(func)
    return out


def discover_registration_runtime_map(*, st: Any | None = None) -> dict[str, Any]:
    """Introspect actual registration callables (Cloud-compatible import order)."""
    out: dict[str, Any] = {"ts": time.time(), "targets": {}, "session_state": {}, "imports": {}}
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_state", None) is not None:
            ss = ctx.session_state
            out["session_state"]["type"] = type(ss).__name__
            out["session_state"]["module"] = type(ss).__module__
            out["session_state"]["mro"] = [c.__name__ for c in type(ss).__mro__[:8]]
            reg = getattr(ss, "register_widget", None)
            if reg is not None:
                out["session_state"]["register_widget"] = _callable_identity(reg)
    except Exception as exc:
        out["session_state"]["error"] = type(exc).__name__

    def _note(name: str, fn: Any) -> None:
        if fn is None:
            return
        out["targets"][name] = _callable_identity(fn)

    try:
        from streamlit.runtime.state import widgets as widgets_mod

        _note("streamlit.runtime.state.widgets.register_widget", widgets_mod.register_widget)
        _note(
            "streamlit.runtime.state.widgets.register_widget_from_metadata",
            widgets_mod.register_widget_from_metadata,
        )
    except Exception as exc:
        out["targets"]["widgets_module_error"] = type(exc).__name__

    try:
        from streamlit.runtime.state import register_widget as state_register_widget

        _note("streamlit.runtime.state.register_widget", state_register_widget)
    except Exception as exc:
        out["targets"]["state_reexport_error"] = type(exc).__name__

    try:
        from streamlit.runtime.state.session_state import SessionState

        _note("SessionState.register_widget", SessionState.register_widget)
    except Exception as exc:
        out["targets"]["SessionState_error"] = type(exc).__name__

    for mod_name in (
        "streamlit.components.v1.custom_component",
        "streamlit.components.v1.components",
        "minimal_component_wake_repro_core",
        "solo_countdown_component",
    ):
        mod = sys.modules.get(mod_name)
        if mod is None:
            out["imports"][mod_name] = "not_loaded"
            continue
        out["imports"][mod_name] = "loaded"
        rw = getattr(mod, "register_widget", None)
        if rw is not None:
            out["targets"][f"{mod_name}.register_widget"] = _callable_identity(rw)
        comp = getattr(mod, "_COMPONENT", None)
        if comp is not None:
            out["targets"][f"{mod_name}._COMPONENT.__call__"] = _callable_identity(
                getattr(comp, "__call__", comp)
            )

    try:
        import minimal_component_wake_repro_core as case_a_mod

        _note("minimal_component_wake_repro_core._COMPONENT.__call__", case_a_mod._COMPONENT.__call__)
    except Exception:
        pass

    return out


def write_registration_runtime_map_files(
    mapping: dict[str, Any],
    *,
    root: Any | None = None,
) -> tuple[str, str]:
    import json
    from pathlib import Path

    base = Path(root) if root else Path(__file__).resolve().parent
    json_path = base / RUNTIME_MAP_JSON
    txt_path = base / RUNTIME_MAP_TXT
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(mapping, indent=2, default=str), encoding="utf-8")
    lines = ["Streamlit registration runtime map", "=" * 40]
    for section, key in (("session_state", "session_state"), ("targets", "targets"), ("imports", "imports")):
        block = mapping.get(section) or {}
        lines.append(f"\n[{section}]")
        lines.append(json.dumps(block, indent=2, default=str))
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return str(json_path), str(txt_path)


def _hook_context(session: dict[str, Any], hook_name: str) -> dict[str, Any]:
    reg_ctx = registration_diag_context(session)
    surface = resolve_diagnostic_surface(
        explicit=str(reg_ctx.get("diagnostic_surface") or session.get("_solo_stage1_last_metadata_surface") or ""),
        component_callable_identity=str(reg_ctx.get("component_callable_identity") or ""),
        widget_key=str(reg_ctx.get("widget_key") or ""),
    )
    return {
        "registration_hook_name": hook_name,
        "diagnostic_surface": surface,
        "declaration_invocation_id": str(reg_ctx.get("declaration_invocation_id") or "")[:80],
        "script_run_seq": int(reg_ctx.get("script_run_seq") or session.get("_solo_stage1_script_run_seq") or 0),
        "diagnostic_run_id": str(session.get("_solo_stage1_run_id") or "")[:32],
        "active_page": str(reg_ctx.get("active_page") or session.get("active_page") or "")[:80],
    }


def _emit_hook_row(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None,
    hook_name: str,
    widget_key: str,
    extra: dict[str, Any],
) -> None:
    base = _hook_context(session, hook_name)
    base.update(extra)
    _emit(session, event, st=st, room=None, widget_key=widget_key, extra=base)


def _metadata_fields_from_register_widget_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    widget_id = str(args[0] if args else kwargs.get("element_id") or "")[:200]
    cb = kwargs.get("on_change_handler")
    out = {
        "authoritative_widget_id": widget_id,
        "metadata_object_type": "register_widget_kwargs",
        "metadata_callback_present": cb is not None,
        "metadata_callback_identity": _fn_identity(cb),
        "callback_args_repr": repr(kwargs.get("args") or ())[:300],
        "callback_kwargs_repr": repr(kwargs.get("kwargs") or {})[:300],
        "value_type": str(kwargs.get("value_type") or ""),
    }
    try:
        from streamlit.runtime.state.common import user_key_from_element_id

        out["user_key"] = str(user_key_from_element_id(widget_id) or "")[:160]
    except Exception:
        out["user_key"] = ""
    return out


def _wrap_callable(
    original: Callable[..., Any],
    hook_name: str,
    *,
    session: dict[str, Any],
    st: Any | None,
    kind: str,
) -> Callable[..., Any]:
    ident = _callable_identity(original)

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        t0 = time.time()
        widget_key = ""
        meta_fields: dict[str, Any] = {}
        if kind == "session_state_metadata":
            metadata = args[0] if args else None
            user_key = args[1] if len(args) > 1 else kwargs.get("user_key")
            meta_fields = snapshot_from_widget_metadata_object(metadata, user_key=str(user_key or ""))
            widget_key = str(meta_fields.get("user_key") or user_key or "")
        elif kind == "register_widget_from_metadata":
            metadata = args[0] if args else None
            meta_fields = snapshot_from_widget_metadata_object(metadata, user_key="")
            widget_key = str(meta_fields.get("user_key") or "")
        else:
            meta_fields = _metadata_fields_from_register_widget_args(args, kwargs)
            widget_key = str(meta_fields.get("user_key") or "")
        if widget_key:
            register_watch_user_key(session, widget_key)
        if kind == "register_widget" and meta_fields.get("metadata_callback_present") is True:
            try:
                from live_draft_streamlit_widget_metadata_diag import METADATA_AT_REGISTRATION

                surface = str(session.get("_solo_delivery_diag_surface") or "case_a_control")
                _emit(
                    session,
                    METADATA_AT_REGISTRATION,
                    st=st,
                    widget_key=widget_key,
                    extra={
                        **meta_fields,
                        "diagnostic_surface": surface,
                        "capture_boundary": "registration_hook_register_widget",
                    },
                )
            except Exception:
                pass
        if kind in ("session_state_metadata", "register_widget_from_metadata") and args:
            try:
                from live_draft_streamlit_widget_metadata_diag import emit_metadata_at_registration

                metadata = args[0]
                user_key_arg = args[1] if len(args) > 1 else kwargs.get("user_key")
                emit_metadata_at_registration(
                    metadata,
                    user_key=str(user_key_arg or widget_key or ""),
                    session=session,
                    st=st,
                )
            except Exception:
                pass
        enter_extra = {
            **ident,
            **meta_fields,
            "hook_kind": kind,
            "timestamp": t0,
        }
        try:
            _emit_hook_row(session, REG_HOOK_ENTERED, st=st, hook_name=hook_name, widget_key=widget_key, extra=enter_extra)
        except Exception:
            pass
        exc_status = ""
        result_type = ""
        try:
            result = original(*args, **kwargs)
            result_type = type(result).__name__
            return result
        except Exception as exc:
            exc_status = f"{type(exc).__name__}:{exc}"[:300]
            raise
        finally:
            exit_extra = {
                **ident,
                **meta_fields,
                "hook_kind": kind,
                "result_type": result_type,
                "exception": exc_status,
                "elapsed_ms": round((time.time() - t0) * 1000.0, 2),
            }
            try:
                _emit_hook_row(session, REG_HOOK_EXITED, st=st, hook_name=hook_name, widget_key=widget_key, extra=exit_extra)
            except Exception:
                pass

    wrapped._solo_registration_hook = hook_name  # type: ignore[attr-defined]
    wrapped._solo_registration_original = original  # type: ignore[attr-defined]
    return wrapped


def install_registration_hooks(st: Any | None, session: dict[str, Any]) -> dict[str, Any]:
    """Patch every discovered registration boundary; emit hooks_installed."""
    if session.get(_HOOK_STATE_KEY, {}).get("installed"):
        return dict(session.get(_HOOK_STATE_KEY) or {})
    if not _diag_enabled(st, session):
        return {"installed": False, "reason": "diag_disabled"}

    report: dict[str, Any] = {
        "installed": False,
        "patched": [],
        "alias_repatches": [],
        "ts": time.time(),
    }
    originals: dict[str, Any] = {}

    def _patch_attr(obj: Any, attr: str, hook_name: str, kind: str) -> bool:
        try:
            current = getattr(obj, attr)
        except Exception:
            return False
        if getattr(current, "_solo_registration_hook", None) == hook_name:
            return False
        wrapped = _wrap_callable(current, hook_name, session=session, st=st, kind=kind)
        originals[hook_name] = current
        setattr(obj, attr, wrapped)
        report["patched"].append(
            {
                "hook_name": hook_name,
                "target": f"{obj.__name__}.{attr}" if hasattr(obj, "__name__") else attr,
                **_callable_identity(current),
                "replacement": _callable_identity(wrapped),
            }
        )
        return True

    try:
        from streamlit.runtime.state import widgets as widgets_mod

        _patch_attr(widgets_mod, "register_widget", "widgets.register_widget", "register_widget")
        _patch_attr(
            widgets_mod,
            "register_widget_from_metadata",
            "widgets.register_widget_from_metadata",
            "register_widget_from_metadata",
        )
        import streamlit.runtime.state as state_pkg

        if hasattr(state_pkg, "register_widget"):
            wrapped = _wrap_callable(
                state_pkg.register_widget,
                "runtime.state.register_widget",
                session=session,
                st=st,
                kind="register_widget",
            )
            originals["runtime.state.register_widget"] = state_pkg.register_widget
            state_pkg.register_widget = wrapped
            report["patched"].append(
                {
                    "hook_name": "runtime.state.register_widget",
                    **_callable_identity(state_pkg.register_widget),
                }
            )
    except Exception as exc:
        report["widgets_patch_error"] = type(exc).__name__

    try:
        from streamlit.runtime.state.session_state import SessionState

        orig = SessionState.register_widget
        if not getattr(orig, "_solo_registration_hook", None):
            wrapped_ss = _wrap_callable(
                orig,
                "SessionState.register_widget",
                session=session,
                st=st,
                kind="session_state_metadata",
            )
            SessionState.register_widget = wrapped_ss  # type: ignore[method-assign]
            originals["SessionState.register_widget"] = orig
            report["patched"].append({"hook_name": "SessionState.register_widget", **_callable_identity(orig)})
    except Exception as exc:
        report["session_state_patch_error"] = type(exc).__name__

    # Re-patch module-local aliases if already imported.
    for mod_name in ("streamlit.components.v1.custom_component", "streamlit.components.v1.components"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        try:
            from streamlit.runtime.state import register_widget as patched_rw

            if getattr(mod, "register_widget", None) is not patched_rw:
                report["alias_repatches"].append(
                    {
                        "module": mod_name,
                        "before": _callable_identity(getattr(mod, "register_widget", None)),
                        "after": _callable_identity(patched_rw),
                    }
                )
                mod.register_widget = patched_rw
        except Exception:
            pass

    report["component_modules_loaded_before_patch"] = {
        name: name in sys.modules
        for name in (
            "streamlit.components.v1.custom_component",
            "minimal_component_wake_repro_core",
            "solo_countdown_component",
        )
    }
    report["installed"] = bool(report["patched"])
    session[_HOOK_STATE_KEY] = report

    runtime_map = discover_registration_runtime_map(st=st)
    report["runtime_map"] = runtime_map
    try:
        from pathlib import Path

        write_registration_runtime_map_files(runtime_map, root=Path(__file__).resolve().parent)
    except Exception:
        pass

    install_row = {
        "patched_callables": report["patched"],
        "original_callable_identities": {k: _fn_identity(v) for k, v in originals.items()},
        "alias_repatches": report.get("alias_repatches"),
        "installation_timestamp": report["ts"],
        "component_modules_loaded_before_patch": report["component_modules_loaded_before_patch"],
        "runtime_map_paths": {
            "json": RUNTIME_MAP_JSON,
            "txt": RUNTIME_MAP_TXT,
        },
    }
    _emit(
        session,
        HOOKS_INSTALLED,
        st=st,
        room=None,
        widget_key="",
        extra=install_row,
    )
    return report


def run_local_case_a_hook_self_test() -> dict[str, Any]:
    """In-process: install hooks and invoke widgets.register_widget once."""
    import streamlit.runtime.state.widgets as widgets_mod
    from streamlit.runtime.state.common import WidgetMetadata

    session: dict[str, Any] = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_script_run_seq": 1,
        REG_DIAG_CTX_KEY: {
            "diagnostic_surface": SURFACE_CASE_A_CONTROL,
            "declaration_invocation_id": "selftest",
            "widget_key": "minimal_wake_repro_0",
            "application_on_change_present": True,
            "application_on_change_identity": "_on_change",
            "component_callable_identity": "minimal_component_wake_repro_core.render_one_cycle",
        },
    }
    events: list[dict[str, Any]] = []

    def _capture_emit(sess: dict, event: str, **kw: Any) -> dict[str, Any]:
        row = {"event": event, **(kw.get("extra") or {})}
        events.append(row)
        return row

    import live_draft_streamlit_widget_metadata_diag as diag_mod

    orig_emit = diag_mod._emit

    def _capture_emit(sess: dict, event: str, **kw: Any) -> dict[str, Any]:
        row = {"event": event, **(kw.get("extra") or {})}
        events.append(row)
        return row

    diag_mod._emit = lambda sess, event, **kw: _capture_emit(sess, event, **kw)  # type: ignore[assignment]

    def _on_change() -> None:
        pass

    install_registration_hooks(None, session)
    element_id = "$$ID-selftest-minimal_wake_repro_0"
    try:
        widgets_mod.register_widget(
            element_id,
            deserializer=lambda x: x,
            serializer=lambda x: x,
            ctx=None,
            on_change_handler=_on_change,
            value_type="json_value",
        )
    except Exception:
        pass
    finally:
        diag_mod._emit = orig_emit

    entered = [e for e in events if e.get("event") == REG_HOOK_ENTERED]
    hooks_installed = [e for e in events if e.get("event") == HOOKS_INSTALLED]
    ok = bool(hooks_installed) and bool(entered) and any(
        e.get("metadata_callback_present") for e in entered
    )
    return {
        "ok": ok,
        "hooks_installed_count": len(hooks_installed),
        "hook_entered_count": len(entered),
        "events": events,
    }
