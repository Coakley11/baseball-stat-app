# Streamlit 1.59.1 — V1 `declare_component` invocation (inspected)

Source: installed package `streamlit/components/v1/custom_component.py` (`CustomComponent.create_instance` / `__call__`).

## Entry

`_COMPONENT = streamlit.components.v1.declare_component(name, path=...)` returns a `CustomComponent` instance; invoking it calls `create_instance`.

## Framework-reserved parameters (not passed as ordinary frontend JSON args)

| Parameter | Consumed by |
|-----------|-------------|
| `key` | Widget identity via `compute_and_register_element_id`; also included in `all_args` sent to frontend as JSON (`default` and `key` are merged into `json_args` for the iframe). |
| `default` | Return fallback when `component_state.value is None`; also serialized to frontend in `json_args`. |
| `on_change` | **`register_widget(..., on_change_handler=on_change)`** — **not** included in `json_args`. Documented: optional callback when widget value changes. |
| `tab_index` | `element.component_instance.tab_index` proto field. |

## Ordinary kwargs

All other `**kwargs` are JSON-ser serialized into `element.component_instance.json_args` for the frontend (`expire_token`, `actionable`, `widget_key`, etc.).

## Return value path (canonical V1)

1. Frontend calls official **`Streamlit.setComponentValue(value)`** (component library), which causes Streamlit to update widget state.
2. Streamlit **reruns** the script.
3. On the rerun, `register_widget` supplies `component_state.value`; `create_instance` returns that value (or `default` if still `None`).

Python excerpt (paraphrased):

```python
component_state = register_widget(..., on_change_handler=on_change, value_type="json_value")
widget_value = component_state.value
if widget_value is None:
    widget_value = default
return widget_value
```

## Implication for Solo countdown frontend

`solo_countdown_component/frontend/index.html` sends expiration via **`window.parent.postMessage({ type: "streamlit:setComponentValue", ... })`** directly. That may produce a **parent postMessage observable** without updating Streamlit widget state or invoking `on_change`. R4/R5 tests distinguish **return-value delivery** from **manual postMessage**.

## Components V2 (future, not migrating now)

Streamlit documents Components V2 with explicit state/trigger callbacks (e.g. trigger + `on_*_change`). Evaluate only after V1 return-value path is characterized on Cloud.
