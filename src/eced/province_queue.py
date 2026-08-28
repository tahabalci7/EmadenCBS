import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.eced import browser


PROVINCES = (
    "ADANA",
    "ADIYAMAN",
    "AFYONKARAHİSAR",
    "AĞRI",
    "AKSARAY",
    "AMASYA",
    "ANKARA",
    "ANTALYA",
    "ARDAHAN",
    "ARTVİN",
    "AYDIN",
    "BALIKESİR",
    "BARTIN",
    "BATMAN",
    "BAYBURT",
    "BİLECİK",
    "BİNGÖL",
    "BİTLİS",
    "BOLU",
    "BURDUR",
    "BURSA",
    "ÇANAKKALE",
    "ÇANKIRI",
    "ÇORUM",
    "DENİZLİ",
    "DİYARBAKIR",
    "DÜZCE",
    "EDİRNE",
    "ELAZIĞ",
    "ERZİNCAN",
    "ERZURUM",
    "ESKİŞEHİR",
    "GAZİANTEP",
    "GİRESUN",
    "GÜMÜŞHANE",
    "HAKKARİ",
    "HATAY",
    "IĞDIR",
    "ISPARTA",
    "İSTANBUL",
    "İZMİR",
    "KAHRAMANMARAŞ",
    "KARABÜK",
    "KARAMAN",
    "KARS",
    "KASTAMONU",
    "KAYSERİ",
    "KIRIKKALE",
    "KIRKLARELİ",
    "KIRŞEHİR",
    "KİLİS",
    "KOCAELİ",
    "KONYA",
    "KÜTAHYA",
    "MALATYA",
    "MANİSA",
    "MARDİN",
    "MERSİN",
    "MUĞLA",
    "MUŞ",
    "NEVŞEHİR",
    "NİĞDE",
    "ORDU",
    "OSMANİYE",
    "RİZE",
    "SAKARYA",
    "SAMSUN",
    "SİİRT",
    "SİNOP",
    "SİVAS",
    "ŞANLIURFA",
    "ŞIRNAK",
    "TEKİRDAĞ",
    "TOKAT",
    "TRABZON",
    "TUNCELİ",
    "UŞAK",
    "VAN",
    "YALOVA",
    "YOZGAT",
    "ZONGULDAK",
)

STATE_PATH = Path("downloads/eced_province_queue_state.json")


class StateError(RuntimeError):
    pass


def _configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue

        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _pending_province_state():
    return {
        "status": "pending",
        "attempts": 0,
        "started_at": None,
        "finished_at": None,
        "last_error": None,
        "project_types": {},
    }


def create_initial_state():
    return {
        "schema_version": 1,
        "updated_at": _timestamp(),
        "provinces": {
            province: _pending_province_state()
            for province in PROVINCES
        },
    }


def state_path_for(download_root=None):
    if download_root is None:
        return STATE_PATH
    return Path(download_root) / STATE_PATH.name


def load_state(state_path=STATE_PATH):
    state_path = Path(state_path)

    if not state_path.exists():
        return create_initial_state()

    try:
        with state_path.open("r", encoding="utf-8") as state_file:
            return json.load(state_file)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StateError(
            f"Geçersiz state dosyası; üzerine yazılmadı: {state_path}"
        ) from exc


def save_state(state, state_path=STATE_PATH):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_name(f"{state_path.name}.tmp")
    state["updated_at"] = _timestamp()

    with temp_path.open("w", encoding="utf-8", newline="\n") as state_file:
        json.dump(
            state,
            state_file,
            ensure_ascii=False,
            indent=2,
        )
        state_file.write("\n")
        state_file.flush()
        os.fsync(state_file.fileno())

    os.replace(temp_path, state_path)


def emit_event(event, province, **details):
    payload = {
        "event": event,
        "province": province,
        **details,
    }
    print(
        "ECED_EVENT "
        + json.dumps(payload, ensure_ascii=False),
        flush=True,
    )


def _summary_error(summaries):
    if not isinstance(summaries, dict):
        return "browser.main geçerli bir summary sözlüğü döndürmedi"

    missing = [
        project_type
        for project_type in ("EK-1", "EK-2")
        if project_type not in summaries
    ]
    if missing:
        return f"Eksik proje türü summary: {', '.join(missing)}"

    for project_type in ("EK-1", "EK-2"):
        summary = summaries[project_type]
        if not isinstance(summary, dict):
            return f"{project_type} summary geçerli değil"

        failed = summary.get("failed")
        if not isinstance(failed, int):
            return f"{project_type} failed değeri geçerli değil"
        if failed > 0:
            return f"{project_type} indirme hatası: {failed}"

    return None


def _mark_in_progress(province_state):
    province_state.update(
        {
            "status": "in_progress",
            "attempts": province_state.get("attempts", 0) + 1,
            "started_at": _timestamp(),
            "finished_at": None,
            "last_error": None,
            "project_types": {},
        }
    )


def _mark_completed(province_state, summaries):
    province_state.update(
        {
            "status": "completed",
            "finished_at": _timestamp(),
            "last_error": None,
            "project_types": summaries,
        }
    )


def _mark_failed(province_state, error, summaries=None):
    province_state.update(
        {
            "status": "failed",
            "finished_at": _timestamp(),
            "last_error": str(error),
            "project_types": summaries or {},
        }
    )


def run_queue(
    state_path=None,
    retry_failed=False,
    province=None,
    downloader=None,
    download_root=None,
):
    if province is not None and province not in PROVINCES:
        raise ValueError(f"Geçersiz il adı: {province}")

    if downloader is None:
        downloader = browser.main

    if state_path is None:
        state_path = state_path_for(download_root)

    state = load_state(state_path)
    province_states = state.get("provinces")
    if not isinstance(province_states, dict):
        raise StateError("State dosyasında geçerli provinces alanı yok")

    targets = (province,) if province is not None else PROVINCES

    for current_province in targets:
        province_state = province_states.get(current_province)
        if not isinstance(province_state, dict):
            province_state = _pending_province_state()
            province_states[current_province] = province_state

        status = province_state.get("status", "pending")
        if status == "completed":
            emit_event(
                "province_skipped",
                current_province,
                reason="completed",
            )
            continue
        if status == "failed" and not retry_failed:
            emit_event(
                "province_skipped",
                current_province,
                reason="failed",
            )
            continue
        if status not in {"pending", "in_progress", "failed"}:
            raise StateError(
                f"{current_province} için geçersiz status: {status}"
            )

        _mark_in_progress(province_state)
        save_state(state, state_path)
        emit_event("province_started", current_province)

        try:
            summaries = downloader(
                current_province,
                download_root=download_root,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            _mark_failed(
                province_state,
                f"{type(exc).__name__}: {exc}",
            )
            save_state(state, state_path)
            emit_event(
                "province_failed",
                current_province,
                error=province_state["last_error"],
            )
            continue

        summary_error = _summary_error(summaries)
        if summary_error is not None:
            stored_summaries = summaries if isinstance(summaries, dict) else None
            _mark_failed(
                province_state,
                summary_error,
                summaries=stored_summaries,
            )
            save_state(state, state_path)
            emit_event(
                "province_failed",
                current_province,
                error=summary_error,
            )
            continue

        _mark_completed(province_state, summaries)
        save_state(state, state_path)
        emit_event(
            "province_completed",
            current_province,
            project_types=summaries,
        )

    return state


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="e-ÇED 81 il indirme kuyruğu",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Daha önce failed olan illeri yeniden çalıştır",
    )
    parser.add_argument(
        "--province",
        help="Yalnız belirtilen canonical ili çalıştır",
    )
    parser.add_argument(
        "--download-root",
        help="PDF arşivi ve queue state dosyası için kök klasör",
    )
    args = parser.parse_args(argv)

    if args.province is not None and args.province not in PROVINCES:
        parser.error(f"Geçersiz il adı: {args.province}")

    return args


def main(argv=None):
    _configure_console_encoding()
    args = parse_args(argv)
    try:
        run_queue(
            retry_failed=args.retry_failed,
            province=args.province,
            download_root=args.download_root,
        )
    except StateError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
