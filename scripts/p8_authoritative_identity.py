"""Authoritative widget identity helpers (ForwardMsg, browser, outbound, active-at-send)."""

from __future__ import annotations

from typing import Any

PROD_KEY = "solo_countdown_wake_solo_persistent"


def full_widget_id(internal_hash: str, user_key: str) -> str:
    h = str(internal_hash or "").strip()
    if not h:
        return ""
    if h.startswith("$$ID-"):
        return h
    return f"$$ID-{h}-{user_key}"


def inbound_forwardmsg_ids_for_key(
    frames: list[dict[str, Any]],
    user_key: str,
    *,
    t0: float = 0.0,
    t1: float | None = None,
) -> list[dict[str, Any]]:
    from p8_streamlit_backmsg_decode import summarize_first_meaningful_inbound

    hits: list[dict[str, Any]] = []
    for f in frames or []:
        if f.get("direction") != "inbound":
            continue
        wt = float(f.get("wall_ts") or 0)
        if wt < t0 or (t1 is not None and wt > t1):
            continue
        raw = f.get("raw_bytes")
        if not isinstance(raw, bytes):
            continue
        if user_key.encode("utf-8") not in raw and b"solo_countdown_wake" not in raw:
            continue
        summ = summarize_first_meaningful_inbound(raw)
        ids = summ.get("widget_ids_in_binary") or []
        prod = [i for i in ids if user_key in str(i.get("user_key_suffix") or "")]
        if not prod:
            continue
        for row in prod:
            hits.append(
                {
                    "wall_ts": wt,
                    "internal_id_hash": row.get("internal_id_hash"),
                    "forwardmsg_element_id": full_widget_id(str(row.get("internal_id_hash") or ""), user_key),
                    "page_script_hash": summ.get("page_script_hash_hint"),
                    "category": summ.get("category") or summ.get("interpretation"),
                    "byte_len": len(raw),
                }
            )
    hits.sort(key=lambda x: float(x.get("wall_ts") or 0))
    return hits


def latest_forwardmsg_element_id(hits: list[dict[str, Any]]) -> tuple[str, float]:
    if not hits:
        return "", 0.0
    last = hits[-1]
    return str(last.get("forwardmsg_element_id") or ""), float(last.get("wall_ts") or 0)


def authoritative_registered_from_declaration(post_row: dict[str, Any]) -> str:
    actual = str(post_row.get("actual_registered_widget_id") or "").strip()
    if actual:
        return actual
    return ""


def compute_active_at_send(
    *,
    send_epoch: float,
    forwardmsg_hits: list[dict[str, Any]],
    outbound_id: str,
    browser_iframe_element_id: str,
    declaration_timeline: list[dict[str, Any]],
    page_script_hash_backmsg: str,
    page_script_hash_declaration: str,
    fragment_id_declaration: str,
    fragment_id_backmsg: str,
) -> dict[str, Any]:
    fwd_id, latest_mount_ts = latest_forwardmsg_element_id(
        [h for h in forwardmsg_hits if str(h.get("forwardmsg_element_id") or "") == outbound_id]
        or forwardmsg_hits
    )
    if not fwd_id and forwardmsg_hits:
        fwd_id, latest_mount_ts = latest_forwardmsg_element_id(forwardmsg_hits)

    later_declarations = [
        r
        for r in declaration_timeline or []
        if float(r.get("ts") or r.get("declaration_ts") or 0) > latest_mount_ts - 0.01
        and float(r.get("ts") or r.get("declaration_ts") or 0) < send_epoch + 0.05
        and str(r.get("event") or "").startswith("production_countdown_declaration_")
    ]
    superseding = [
        r
        for r in later_declarations
        if str(r.get("actual_registered_widget_id") or r.get("predicted_element_id") or "")
        and str(r.get("actual_registered_widget_id") or r.get("predicted_element_id") or "") != outbound_id
    ]

    hash_ok = (
        not page_script_hash_declaration
        or not page_script_hash_backmsg
        or page_script_hash_declaration == page_script_hash_backmsg
    )
    fragment_ok = not fragment_id_declaration or fragment_id_declaration == (fragment_id_backmsg or "")

    ids_align = bool(
        outbound_id
        and fwd_id
        and outbound_id.strip() == fwd_id.strip()
        and browser_iframe_element_id
        and browser_iframe_element_id.strip() == outbound_id.strip()
    )
    mount_before_send = latest_mount_ts > 0 and latest_mount_ts < send_epoch + 0.05
    no_supersede = len(superseding) == 0 and len(later_declarations) <= 2

    active = bool(ids_align and mount_before_send and no_supersede and hash_ok and fragment_ok)

    return {
        "active_at_send": active,
        "latest_mount_ts": latest_mount_ts,
        "forwardmsg_element_id_at_mount": fwd_id,
        "outbound_backmsg_widget_id": outbound_id,
        "browser_iframe_element_id": browser_iframe_element_id,
        "mount_before_send": mount_before_send,
        "iframe_id_matches_outbound": browser_iframe_element_id.strip() == outbound_id.strip()
        if browser_iframe_element_id and outbound_id
        else False,
        "forwardmsg_matches_outbound": fwd_id.strip() == outbound_id.strip() if fwd_id and outbound_id else False,
        "later_declaration_count": len(later_declarations),
        "superseding_declaration_count": len(superseding),
        "page_script_hash_match": hash_ok,
        "fragment_id_match": fragment_ok,
    }


def classify_authoritative(
    report: dict[str, Any],
) -> dict[str, Any]:
    if not report.get("control_gate", {}).get("ok"):
        return {
            "code": "S10",
            "rationale": "Control canary path failed on deployed build.",
            "smallest_correction_boundary": "Observability / control gate",
        }
    prod = report.get("production") or {}
    active = (report.get("active_at_send_proof") or {}).get("active_at_send")
    ids = report.get("production_identity") or {}
    triple_equal = ids.get("authoritative_triple_equal") is True
    ctrl_globals = int((report.get("control") or {}).get("post_send_global_canary_count") or 0)
    prod_globals = int(prod.get("post_send_global_canary_count") or 0)
    prod_branch = int(prod.get("post_send_branch_canary_count") or 0)

    if triple_equal and active is False:
        if (report.get("active_at_send_proof") or {}).get("superseding_declaration_count", 0) > 0:
            return {
                "code": "S4",
                "rationale": "Another declaration superseded the sender before expiration.",
                "smallest_correction_boundary": "Duplicate user key / redeclaration",
            }
        return {
            "code": "S2",
            "rationale": "Authoritative IDs align but component not active at send.",
            "smallest_correction_boundary": "Mount lifecycle / iframe connection at send",
        }

    if prod.get("server_dedupe_hint"):
        return {
            "code": "S6",
            "rationale": "Backend may treat widget update as unchanged.",
            "smallest_correction_boundary": "Widget-state dedupe",
        }

    if triple_equal and active and ctrl_globals >= 1 and prod_globals == 0:
        return {
            "code": "S9A",
            "rationale": (
                "Control canary path passes; production authoritative IDs match; "
                "component active_at_send; valid BackMsg sent; zero post-send global canaries."
            ),
            "smallest_correction_boundary": "Server widget-state acceptance -> full script run",
        }
    if prod_globals > 0 and prod_branch == 0:
        return {
            "code": "S9B",
            "rationale": "Global canary observed post-send but Live Draft branch canary absent.",
            "smallest_correction_boundary": "LDR branch entry after script run",
        }
    if prod_globals > 0 and prod_branch > 0 and prod.get("python_return_empty_hint"):
        return {
            "code": "S9C",
            "rationale": "Script and LDR branch ran but component return/session state empty.",
            "smallest_correction_boundary": "Component return / session state bind",
        }
    if prod.get("p8c7_rejects_token"):
        return {
            "code": "S9D",
            "rationale": "Token present but P8C7 declaration snapshot validation fails.",
            "smallest_correction_boundary": "P8C7 snapshot validation",
        }
    if prod.get("p8c7_chain_passes"):
        return {
            "code": "S9E",
            "rationale": "Exact token validates through P8C7 chain.",
            "smallest_correction_boundary": "Post-bind flush / downstream",
        }
    if ctrl_globals >= 1 and prod_globals == 0 and not triple_equal:
        return {
            "code": "S10",
            "rationale": "Control path OK but production identity triple incomplete.",
            "smallest_correction_boundary": "Authoritative identity capture",
        }
    return {
        "code": "S9A",
        "rationale": str(report.get("first_difference") or "See production backend surfaces."),
        "smallest_correction_boundary": "Backend Python outcome after valid widget update",
    }
