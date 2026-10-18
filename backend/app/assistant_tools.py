from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import BODY_REID_THRESHOLD, WAKE_CONTEXT_SECONDS
from .db import connection


@dataclass(slots=True)
class CommandAnswer:
    text: str
    intent: str
    certainty: str = "system"
    person_id: int | None = None


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in value).split())


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _looks_like_time_question(q: str) -> bool:
    """Recognize natural/Whisper variants of a request for the current time.

    Tiny Whisper commonly varies plural/agreement ("que hora sao"), drops
    function words ("horas agora") or chooses "horario". During the Tonho
    command window, a time word plus a question/request cue is sufficiently
    specific and much safer than requiring one exact sentence.
    """
    tokens = q.split()
    if not tokens:
        return False
    time_tokens = {
        "hora", "horas", "horario", "horarios", "horasao", "horassao",
    }
    has_time_word = any(token in time_tokens or token.startswith("hora") for token in tokens)
    if not has_time_word:
        return False
    if len(tokens) <= 2:
        return True
    cues = {"que", "qual", "quais", "agora", "sao", "e", "eh", "me", "diz", "diga", "fala", "fale"}
    return bool(cues.intersection(tokens)) or _contains_any(
        q,
        (
            "que hora", "qual hora", "qual horario", "que horario",
            "hora agora", "horas agora", "me diz a hora", "me fala a hora",
        ),
    )


def detect_intent(text: str, person_names: list[str] | None = None) -> tuple[str, str | None]:
    q = normalize_text(text)
    if not q:
        return "empty", None

    if _contains_any(q, ("o que voce sabe fazer", "o que voce faz", "quais comandos", "me ajuda", "ajuda tonho")):
        return "help", None
    if _looks_like_time_question(q):
        return "time", None
    if _contains_any(q, ("quem sou eu", "voce sabe quem eu sou", "sabe quem eu sou")):
        return "who_am_i", None
    if _contains_any(q, ("quem esta aqui", "quem ta aqui", "quem esta ai", "quem ta ai", "quem voce esta vendo", "quem voce ve")):
        return "who_is_here", None
    if ("quem" in q and "pass" in q and "hoje" in q) or _contains_any(q, ("quem apareceu aqui hoje", "quem apareceu hoje")):
        return "who_today", None
    if _contains_any(q, ("quantas pessoas passaram hoje", "quantas pessoas apareceram hoje", "quantos passaram hoje", "quantas passaram hoje")):
        return "count_today", None
    if _contains_any(q, ("tem alguem desconhecido", "ha alguem desconhecido", "alguem desconhecido hoje", "viu alguem desconhecido", "viu alguem que nao conhece")):
        return "unknown_today", None
    if _contains_any(q, ("qual seu nome", "como voce se chama", "quem e voce")):
        return "assistant_name", None

    if person_names and _contains_any(q, ("quando", "ultima vez", "passou", "apareceu", "viu")):
        matches: list[tuple[int, str]] = []
        for name in person_names:
            normalized_name = normalize_text(name)
            if normalized_name and normalized_name in q:
                matches.append((len(normalized_name), name))
        if matches:
            matches.sort(reverse=True)
            return "last_seen", matches[0][1]

    return "unknown", None


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _local_now(timezone_name: str | None) -> datetime:
    return datetime.now(_zone(timezone_name))


def _today_bounds(timezone_name: str | None) -> tuple[str, str]:
    local_now = _local_now(timezone_name)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc).isoformat(), end_local.astimezone(timezone.utc).isoformat()


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except Exception:
        return None


def _join_names(names: list[str]) -> str:
    clean = list(dict.fromkeys(name for name in names if name))
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} e {clean[1]}"
    return ", ".join(clean[:-1]) + f" e {clean[-1]}"


def _recent_rows(camera_id: int) -> list[Any]:
    with connection() as conn:
        return conn.execute(
            """SELECT e.created_at, e.identity_state, e.unknown_cluster_id,
                e.person_id, e.probable_person_id, e.body_confidence,
                p.name AS person_name, pp.name AS probable_person_name
            FROM events e
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN persons pp ON pp.id = e.probable_person_id
            WHERE e.camera_id = ? AND COALESCE(e.identity_state, '') <> 'false_positive'
            ORDER BY e.created_at DESC LIMIT 40""",
            (camera_id,),
        ).fetchall()


def _current_subjects(camera_id: int) -> tuple[list[tuple[int, str]], list[tuple[int, str]], int]:
    now = datetime.now(timezone.utc)
    known: list[tuple[int, str]] = []
    probable: list[tuple[int, str]] = []
    unknown = 0
    seen_known: set[int] = set()
    seen_probable: set[int] = set()
    for row in _recent_rows(camera_id):
        created = _parse_iso(str(row["created_at"] or ""))
        if created is None or (now - created).total_seconds() > WAKE_CONTEXT_SECONDS:
            continue
        if row["person_id"] is not None and row["person_name"]:
            person_id = int(row["person_id"])
            if person_id not in seen_known:
                known.append((person_id, str(row["person_name"])))
                seen_known.add(person_id)
            continue
        if (
            row["probable_person_id"] is not None
            and row["probable_person_name"]
            and float(row["body_confidence"] or 0.0) >= BODY_REID_THRESHOLD
        ):
            person_id = int(row["probable_person_id"])
            if person_id not in seen_known and person_id not in seen_probable:
                probable.append((person_id, str(row["probable_person_name"])))
                seen_probable.add(person_id)
            continue
        unknown += 1
    return known, probable, unknown


def _today_rows(camera_id: int, timezone_name: str | None) -> list[Any]:
    start, end = _today_bounds(timezone_name)
    with connection() as conn:
        return conn.execute(
            """SELECT e.created_at, e.identity_state, e.unknown_cluster_id, e.track_id,
                e.person_id, e.probable_person_id, e.body_confidence,
                p.name AS person_name, pp.name AS probable_person_name
            FROM events e
            LEFT JOIN persons p ON p.id = e.person_id
            LEFT JOIN persons pp ON pp.id = e.probable_person_id
            WHERE e.camera_id = ? AND e.created_at >= ? AND e.created_at < ?
              AND COALESCE(e.identity_state, '') <> 'false_positive'
            ORDER BY e.created_at ASC""",
            (camera_id, start, end),
        ).fetchall()


def _today_summary(camera_id: int, timezone_name: str | None) -> dict[str, Any]:
    known: dict[int, str] = {}
    probable: dict[int, str] = {}
    unknown_events = 0
    unknown_clusters: set[str] = set()
    for row in _today_rows(camera_id, timezone_name):
        if row["person_id"] is not None and row["person_name"]:
            person_id = int(row["person_id"])
            known[person_id] = str(row["person_name"])
            probable.pop(person_id, None)
            continue
        if (
            row["probable_person_id"] is not None
            and row["probable_person_name"]
            and float(row["body_confidence"] or 0.0) >= BODY_REID_THRESHOLD
        ):
            person_id = int(row["probable_person_id"])
            if person_id not in known:
                probable[person_id] = str(row["probable_person_name"])
            continue
        unknown_events += 1
        if row["unknown_cluster_id"] is not None:
            unknown_clusters.add(f"cluster:{int(row['unknown_cluster_id'])}")
        elif row["track_id"] is not None:
            unknown_clusters.add(f"track:{int(row['track_id'])}")
    return {
        "known": known,
        "probable": probable,
        "unknown_events": unknown_events,
        "unknown_subjects": len(unknown_clusters),
    }


def _format_seen_time(raw: str, timezone_name: str | None) -> str:
    seen = _parse_iso(raw)
    if seen is None:
        return "em um horário que não consegui interpretar"
    local_seen = seen.astimezone(_zone(timezone_name))
    local_now = _local_now(timezone_name)
    clock = local_seen.strftime("%H:%M")
    if local_seen.date() == local_now.date():
        return f"hoje às {clock}"
    if local_seen.date() == (local_now.date() - timedelta(days=1)):
        return f"ontem às {clock}"
    return f"em {local_seen.strftime('%d/%m')} às {clock}"


def _person_names() -> list[str]:
    with connection() as conn:
        rows = conn.execute("SELECT name FROM persons ORDER BY LENGTH(name) DESC, name COLLATE NOCASE").fetchall()
    return [str(row["name"]) for row in rows if row["name"]]


def answer_command(camera_id: int, text: str, timezone_name: str | None = None) -> CommandAnswer:
    intent, person_name = detect_intent(text, _person_names())

    if intent == "help":
        return CommandAnswer(
            "Por enquanto você pode perguntar quem você é, quem está aqui, quem passou aqui hoje, quando alguém passou, quantas pessoas passaram hoje, se há desconhecidos e que horas são.",
            intent,
        )
    if intent == "assistant_name":
        return CommandAnswer("Eu sou o Tonho.", intent)
    if intent == "time":
        now = _local_now(timezone_name)
        return CommandAnswer(f"Agora são {now.strftime('%H:%M')}.", intent)
    if intent == "who_am_i":
        known, probable, _ = _current_subjects(camera_id)
        if known:
            return CommandAnswer(f"Você é {known[0][1]}.", intent, "known", known[0][0])
        if probable:
            return CommandAnswer(f"Acho que você é {probable[0][1]}.", intent, "probable", probable[0][0])
        return CommandAnswer("Ainda não sei quem você é.", intent, "unknown")
    if intent == "who_is_here":
        known, probable, unknown = _current_subjects(camera_id)
        if known:
            text_out = f"Estou vendo {_join_names([name for _, name in known])}."
            if probable:
                text_out += f" Acho que também está aqui {_join_names([name for _, name in probable])}."
            return CommandAnswer(text_out, intent, "known", known[0][0])
        if probable:
            return CommandAnswer(
                f"Acho que estou vendo {_join_names([name for _, name in probable])}.",
                intent,
                "probable",
                probable[0][0],
            )
        if unknown:
            return CommandAnswer("Tem alguém aqui, mas ainda não reconheci quem é.", intent, "unknown")
        return CommandAnswer("Não estou vendo ninguém identificado aqui agora.", intent, "unknown")
    if intent == "who_today":
        summary = _today_summary(camera_id, timezone_name)
        parts: list[str] = []
        known_names = list(summary["known"].values())
        probable_names = list(summary["probable"].values())
        if known_names:
            parts.append(f"Hoje identifiquei {_join_names(known_names)}.")
        if probable_names:
            parts.append(f"Provavelmente também vi {_join_names(probable_names)}.")
        if summary["unknown_events"]:
            count = int(summary["unknown_events"])
            parts.append(f"Também tenho {count} {'detecção' if count == 1 else 'detecções'} que ainda não identifiquei.")
        if not parts:
            parts.append("Ainda não registrei ninguém por aqui hoje.")
        return CommandAnswer(" ".join(parts), intent)
    if intent == "count_today":
        summary = _today_summary(camera_id, timezone_name)
        known_count = len(summary["known"])
        probable_count = len(summary["probable"])
        unknown_events = int(summary["unknown_events"])
        parts = [f"Hoje identifiquei {known_count} {'pessoa conhecida' if known_count == 1 else 'pessoas conhecidas'} diferentes."]
        if probable_count:
            parts.append(f"Tenho ainda {probable_count} {'identificação provável' if probable_count == 1 else 'identificações prováveis'}.")
        if unknown_events:
            parts.append(f"E há {unknown_events} {'detecção sem identificação' if unknown_events == 1 else 'detecções sem identificação'}.")
        return CommandAnswer(" ".join(parts), intent)
    if intent == "unknown_today":
        summary = _today_summary(camera_id, timezone_name)
        count = int(summary["unknown_events"])
        if count:
            return CommandAnswer(f"Sim. Tenho {count} {'detecção ainda não identificada' if count == 1 else 'detecções ainda não identificadas'} hoje.", intent, "unknown")
        return CommandAnswer("Não. Até agora não tenho detecções desconhecidas hoje.", intent)
    if intent == "last_seen" and person_name:
        with connection() as conn:
            person = conn.execute("SELECT id, name FROM persons WHERE name = ? COLLATE NOCASE LIMIT 1", (person_name,)).fetchone()
            if person is None:
                return CommandAnswer(f"Não encontrei {person_name} na minha base.", intent)
            row = conn.execute(
                """SELECT e.created_at, e.person_id, e.probable_person_id
                FROM events e
                WHERE e.camera_id = ? AND COALESCE(e.identity_state, '') <> 'false_positive'
                  AND (e.person_id = ? OR (e.person_id IS NULL AND e.probable_person_id = ?))
                ORDER BY e.created_at DESC LIMIT 1""",
                (camera_id, int(person["id"]), int(person["id"])),
            ).fetchone()
        if row is None:
            return CommandAnswer(f"Ainda não registrei {person['name']} por aqui.", intent, "unknown", int(person["id"]))
        when = _format_seen_time(str(row["created_at"]), timezone_name)
        if row["person_id"] is not None:
            return CommandAnswer(f"{person['name']} apareceu por aqui pela última vez {when}.", intent, "known", int(person["id"]))
        return CommandAnswer(f"Acho que {person['name']} apareceu por aqui pela última vez {when}.", intent, "probable", int(person["id"]))

    return CommandAnswer(
        "Ainda não sei responder essa pergunta. Por enquanto posso responder coisas simples sobre quem está aqui e o histórico desta câmera.",
        "unknown",
    )
