"""Eval-style tests for GitHub issue #62 (multi-language support).

Unlike the rest of the suite, this module calls the *real* Claude API — the
whole point is to check whether the agent actually keeps responding in the
requested language across a multi-turn conversation, which a mocked
`anthropic.Anthropic` client can't tell us anything about. To keep it from
becoming a live-network-dependent CI dependency:

  - The module is skipped entirely unless ANTHROPIC_API_KEY is configured
    (same signal app/config.py already reads via python-dotenv). CI's
    tests.yml workflow never sets this, so `pytest -m "not integration"` and
    `pytest -m integration` both skip it there; it only runs for a developer
    who has exported a real key locally.
  - Tool-backed data (school website scrape, calendar RSS, no-school days) is
    mocked with canned content, same as tests/test_agent.py and
    tests/test_date_handling.py — this eval is about language, not about
    scraping wms.dublinusd.org or hitting a live RSS feed on every run.
  - get_campus_directions is NOT mocked — it just reads the bundled
    campus_map.json fixture, so campus questions exercise a real tool call.

Run explicitly with a key set:
    ANTHROPIC_API_KEY=sk-... pytest tests/test_language_eval.py -v

Language detection is a coarse heuristic (see _assert_in_language below), not
a real language identifier — good enough to catch "drifted back to English"
regressions, which is what issue #62's acceptance criteria actually calls for.
"""
import re
from unittest.mock import MagicMock, patch

import pytest

from app import config
from app.agent import SchoolAgent
from app.schools import get_school
from app.store.redis_store import RedisStore
from tests.store.conftest import FakeRedisClient

pytestmark = pytest.mark.skipif(
    not config.ANTHROPIC_API_KEY,
    reason="requires a real ANTHROPIC_API_KEY to call the live Claude API",
)

CANNED_SCHOOL_INFO = (
    "Wells Middle School office hours are Monday-Friday, 8:00 AM to 4:00 PM. "
    "Main phone: (925) 828-6227. The front office is in the Administration "
    "building. Clubs include Chess Club, Robotics Club, and Art Club, each "
    "meeting weekly after school."
)
CANNED_EVENTS = (
    "- 2026-11-06 (Friday): Fall Concert, 6:00 PM, Wells Middle School Gym\n"
    "- 2026-11-13 (Friday): PTA Meeting, 9:00 AM, Library\n"
    "- 2026-12-04 (Friday): Winter Dance, 7:00 PM, Cafeteria"
)
CANNED_NO_SCHOOL_DAYS = (
    "- 2026-11-11 (Wednesday): Veterans Day Holiday\n"
    "- 2026-11-23 (Monday) - 2026-11-29 (Sunday): Thanksgiving Break"
)

CJK_RE = re.compile(r"[一-鿿]")
ENGLISH_MARKERS = {
    "the", "is", "are", "and", "you", "your", "please", "thanks", "thank",
    "what", "when", "where", "how", "school", "today", "tomorrow", "hello",
    "here", "office", "hours",
}
SPANISH_MARKERS = {
    "el", "la", "los", "las", "de", "del", "que", "para", "con", "es", "son",
    "hoy", "mañana", "escuela", "gracias", "por", "favor", "cuándo", "cuando",
    "dónde", "donde", "cómo", "como", "una", "un", "en", "y", "se", "más",
}


def _assert_in_language(text: str, language: str) -> None:
    """Coarse language check: strips URLs (domain names are Latin-script
    regardless of response language and would skew detection), then applies
    a per-language heuristic. Not a substitute for a real language
    identifier, but sufficient to catch "the agent drifted back to English"
    regressions, which is what this eval exists to catch."""
    cleaned = re.sub(r"https?://\S+", "", text)

    if language == "zh":
        cjk_count = len(CJK_RE.findall(cleaned))
        letters = len(re.findall(r"[^\W\d_]", cleaned, re.UNICODE))
        assert letters > 0, f"empty/non-text response: {text!r}"
        assert cjk_count / letters > 0.3, (
            f"expected a mostly-Chinese response, got only "
            f"{cjk_count}/{letters} CJK characters: {text!r}"
        )
    elif language == "es":
        assert not CJK_RE.search(cleaned), f"unexpected CJK in Spanish response: {text!r}"
        words = re.findall(r"[a-záéíóúñü]+", cleaned.lower())
        spanish_hits = sum(1 for w in words if w in SPANISH_MARKERS)
        english_hits = sum(1 for w in words if w in ENGLISH_MARKERS)
        assert spanish_hits >= 2, (
            f"expected recognizable Spanish function words, found none of "
            f"{sorted(SPANISH_MARKERS)} in: {text!r}"
        )
        assert english_hits <= 2, (
            f"too many English marker words ({english_hits}) in a Spanish "
            f"response: {text!r}"
        )
    else:
        raise ValueError(f"unsupported language for eval assertion: {language!r}")


# 20 Spanish questions covering events, calendar, campus, and lunch — the
# intents called out in issue #62.
SPANISH_QUESTIONS = [
    "¿Cuándo es el próximo evento escolar?",
    "¿Hay clases mañana?",
    "¿Cuál es el horario de almuerzo?",
    "¿Dónde está la biblioteca?",
    "¿Cuáles son las próximas vacaciones o días sin clases?",
    "¿A qué hora empieza la escuela los lunes?",
    "¿Cómo llego del salón B101 al gimnasio?",
    "¿Cuándo termina el año escolar?",
    "¿Qué días hay medio día de clases?",
    "¿Dónde puedo ver el calendario escolar completo?",
    "¿Hay algún evento este fin de semana?",
    "¿Cuál es el número de teléfono de la escuela?",
    "¿Dónde está la oficina principal?",
    "¿Qué clubes hay disponibles para estudiantes?",
    "¿Cuándo es el primer día de clases del próximo año escolar?",
    "¿Cuánto dura el período de almuerzo?",
    "¿Hay algún día festivo este mes?",
    "¿Dónde queda el salón de la clase de ciencias?",
    "¿A qué hora termina el horario mínimo?",
    "¿Cuáles son los horarios de oficina de la escuela?",
]

# 20 Mandarin (Simplified Chinese) questions, same intent coverage.
MANDARIN_QUESTIONS = [
    "下一个学校活动是什么时候？",
    "明天有课吗？",
    "午餐时间是几点？",
    "图书馆在哪里？",
    "接下来的假期或不上课的日子是什么时候？",
    "周一几点开始上课？",
    "从B101教室怎么去体育馆？",
    "这个学年什么时候结束？",
    "哪些日子是半天上课？",
    "在哪里可以看到完整的学校日历？",
    "这个周末有活动吗？",
    "学校的电话号码是多少？",
    "校长办公室在哪里？",
    "学生可以参加哪些社团？",
    "下个学年的开学第一天是什么时候？",
    "午餐时间有多长？",
    "这个月有假期吗？",
    "科学教室在哪栋楼？",
    "提前放学日几点结束？",
    "学校的办公时间是什么时候？",
]


@pytest.fixture()
def live_agent():
    """A real SchoolAgent with a real anthropic.Anthropic client (using
    config.ANTHROPIC_API_KEY), but a fake Redis client and mocked Postgres —
    no real Redis/Postgres needed for a language eval."""
    return SchoolAgent(
        school=get_school("wells"),
        redis_store=RedisStore(client=FakeRedisClient()),
        postgres_store=MagicMock(),
    )


def _run_eval(agent: SchoolAgent, questions: list[str], language: str, user_id: str) -> list[tuple[str, str, bool]]:
    """Runs every question as one multi-turn conversation (same user_id) —
    this also exercises the acceptance criterion that the language directive
    holds across turns, not just on the first message. `language` is only
    passed on the first call; later calls rely purely on what got persisted,
    same as a real chatbox session after the toggle is set once."""
    results = []
    for i, question in enumerate(questions):
        reply = agent.chat(
            question,
            user_id=user_id,
            language=language if i == 0 else None,
        )
        try:
            _assert_in_language(reply.text, language)
            results.append((question, reply.text, True))
        except AssertionError as e:
            results.append((question, reply.text, False))
            print(f"[{language}] FAIL: {question!r} -> {e}")
    return results


def _mocked_tools():
    return (
        patch("app.agent.get_school_day_status", return_value="Regular school day"),
        patch("app.agent.get_today_status", return_value=""),
        patch("app.agent.get_upcoming_events", return_value=CANNED_EVENTS),
        patch("app.agent.get_upcoming_no_school_days", return_value=CANNED_NO_SCHOOL_DAYS),
    )


def test_spanish_eval_set_stays_in_spanish(live_agent):
    with patch.object(live_agent.scraper, "get_school_info", return_value=CANNED_SCHOOL_INFO), \
         patch("app.agent.get_school_day_status", return_value="Regular school day"), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=CANNED_EVENTS), \
         patch("app.agent.get_upcoming_no_school_days", return_value=CANNED_NO_SCHOOL_DAYS):
        results = _run_eval(live_agent, SPANISH_QUESTIONS, "es", user_id="eval_es")

    passed = sum(1 for _, _, ok in results if ok)
    print(f"\nSpanish eval: {passed}/{len(results)} responses stayed in Spanish")
    failures = [q for q, _, ok in results if not ok]
    assert not failures, f"{len(failures)} response(s) drifted out of Spanish: {failures}"


def test_mandarin_eval_set_stays_in_mandarin(live_agent):
    with patch.object(live_agent.scraper, "get_school_info", return_value=CANNED_SCHOOL_INFO), \
         patch("app.agent.get_school_day_status", return_value="Regular school day"), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=CANNED_EVENTS), \
         patch("app.agent.get_upcoming_no_school_days", return_value=CANNED_NO_SCHOOL_DAYS):
        results = _run_eval(live_agent, MANDARIN_QUESTIONS, "zh", user_id="eval_zh")

    passed = sum(1 for _, _, ok in results if ok)
    print(f"\nMandarin eval: {passed}/{len(results)} responses stayed in Mandarin Chinese")
    failures = [q for q, _, ok in results if not ok]
    assert not failures, f"{len(failures)} response(s) drifted out of Mandarin Chinese: {failures}"
