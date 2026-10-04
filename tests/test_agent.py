"""Unit tests for SchoolAgent."""
from dataclasses import replace
from unittest.mock import MagicMock, patch, call
import pytest

import app.agent as agent_module
from app.agent import SchoolAgent
from app.schools import get_school
from app.store.redis_store import RedisStore
from tests.store.conftest import FakeRedisClient


@pytest.fixture()
def agent():
    with patch("app.agent.anthropic.Anthropic"):
        redis_store = RedisStore(client=FakeRedisClient())
        postgres_store = MagicMock()
        return SchoolAgent(
            school=get_school("wells"),
            redis_store=redis_store,
            postgres_store=postgres_store,
        )


@pytest.fixture()
def dhs_agent():
    with patch("app.agent.anthropic.Anthropic"):
        redis_store = RedisStore(client=FakeRedisClient())
        postgres_store = MagicMock()
        return SchoolAgent(
            school=get_school("dhs"),
            redis_store=redis_store,
            postgres_store=postgres_store,
        )


@pytest.fixture()
def agent_without_campus_map():
    """A school with no campus_map_file configured, to exercise the tool-omission path."""
    with patch("app.agent.anthropic.Anthropic"):
        redis_store = RedisStore(client=FakeRedisClient())
        postgres_store = MagicMock()
        school = replace(get_school("dhs"), campus_map_file=None)
        return SchoolAgent(
            school=school,
            redis_store=redis_store,
            postgres_store=postgres_store,
        )


def _text_response(text: str):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=text, type="text")]
    return mock_response


# ── Prompt caching: system prompt is static ───────────────────────────────────

def test_system_prompt_has_no_today_placeholder(agent):
    assert "{today}" not in agent._system_prompt


def test_system_prompt_is_stable_across_calls(agent):
    first = agent._system_prompt
    second = agent._system_prompt
    assert first == second


def test_system_prompt_allows_markdown(agent):
    assert "Markdown" in agent._system_prompt
    assert "**bold**" in agent._system_prompt


def test_system_prompt_guards_yesno_contradiction_beyond_just_school_day(agent):
    """PR #132 added a rule against opening with 'Yes/No' before checking
    tool data, but scoped it to 'is there school on a given day' — leaving
    the same failure pattern open for other day-shaped yes/no questions
    like 'is tomorrow a Grady day?', 'is Friday a minimum day?', etc.
    A real production reply was seen with 'No, tomorrow is not a Grady
    Day. Tomorrow is Wednesday, September 23, 2026, which is a Grady Day'
    — an outright self-contradiction. This test guards the generalized
    rule so a future refactor doesn't narrow the scope back to school-day
    only."""
    prompt = agent._system_prompt
    # Original school-day case is still called out (not removed).
    assert "is there school tomorrow" in prompt
    # Grady day is named explicitly so anyone reading the rule sees the
    # broader intent, not just school days.
    assert "Grady day" in prompt
    # The rule explicitly generalizes to "ANY yes/no question" not "a
    # yes/no question" — that word matters, it's the load-bearing scope
    # widener.
    assert "ANY yes/no question" in prompt
    # The exact real-production string that triggered this fix is quoted
    # in the rule so a future maintainer knows what the wording is
    # defending against — deleting the quote should require a good reason.
    assert "which IS a Grady Day" in prompt


def test_chat_uses_system_prompt(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="u_web")

    _, kwargs = agent.client.beta.messages.create.call_args
    assert kwargs["system"][0]["text"] == agent._system_prompt


# ── Per-school content ─────────────────────────────────────────────────────────

def test_system_prompt_is_specific_to_school(agent, dhs_agent):
    assert "Wells Middle School" in agent._system_prompt
    assert "Dublin High School" in dhs_agent._system_prompt
    assert agent._system_prompt != dhs_agent._system_prompt


def test_get_school_information_page_group_enum_includes_new_groups(agent):
    """Sitemap-discovery passes (#116, #117) added athletics/family/enrollment/
    technology as real page groups both DHS and Wells have content for — the
    shared tool schema (every school uses the same get_school_information
    definition) must expose them as valid page_group values."""
    tool = next(t for t in agent.tools if t["name"] == "get_school_information")
    enum = tool["input_schema"]["properties"]["page_group"]["enum"]
    assert "athletics" in enum
    assert "family" in enum
    assert "enrollment" in enum
    assert "technology" in enum


def test_dhs_pages_has_new_page_groups_populated():
    """Data-integrity check on data/schools/dhs/school.json: the new groups
    must actually have URLs, not just exist as empty/placeholder keys."""
    dhs = get_school("dhs")
    assert len(dhs.pages["athletics"]) >= 1
    assert len(dhs.pages["family"]) >= 1
    assert len(dhs.pages["enrollment"]) >= 1
    assert len(dhs.pages["technology"]) >= 1


def test_wells_pages_has_new_page_groups_populated():
    """Data-integrity check on data/schools/wells/school.json: the new groups
    added by Wells' own sitemap-discovery pass (#117) must actually have
    URLs, not just exist as empty/placeholder keys."""
    wells = get_school("wells")
    assert len(wells.pages["athletics"]) >= 1
    assert len(wells.pages["family"]) >= 1
    assert len(wells.pages["enrollment"]) >= 1
    assert len(wells.pages["technology"]) >= 1


def test_missing_page_group_falls_back_to_home():
    """A page_group with no populated URLs must silently fall back to the
    school's home page(s), not KeyError — the tool schema's enum can grow
    ahead of any single school's sitemap-discovery pass."""
    wells = get_school("wells")
    fallback = wells.pages.get("nonexistent_group", wells.pages.get("home", []))
    assert fallback == wells.pages["home"]


def test_system_prompt_cites_bell_schedule_url_for_bell_schedule_questions(agent, dhs_agent):
    """Bell schedule questions must cite the school's actual bell-schedule
    page/document (school.bell_schedule_url), not the generic site root —
    a parent needs to be able to cross-check exact times."""
    assert "bell schedule questions: 📍 [Source](https://drive.google.com/file/d/1ylPRVuaMTKY0Y9_iyOqpC0nkVpmH6ZWN/view)" in agent._system_prompt
    assert "bell schedule questions: 📍 [Source](https://dhs.dublinusd.org/apps/bell_schedules/)" in dhs_agent._system_prompt


def test_system_prompt_bell_schedule_source_falls_back_to_website_when_unset(agent):
    school = replace(agent.school, bell_schedule_url=None)
    prompt = SchoolAgent._build_system_prompt(school)
    assert f"bell schedule questions: 📍 [Source]({school.website})" in prompt


def test_get_campus_directions_tool_omitted_when_school_has_no_campus_map(agent_without_campus_map):
    assert "get_campus_directions" not in [t["name"] for t in agent_without_campus_map.tools]


def test_get_campus_directions_tool_present_when_school_has_campus_map(agent, dhs_agent):
    assert "get_campus_directions" in [t["name"] for t in agent.tools]
    assert "get_campus_directions" in [t["name"] for t in dhs_agent.tools]


def test_get_campus_directions_parses_dhs_campus_map(dhs_agent):
    with patch("app.agent.config.PUBLIC_BASE_URL", ""):
        result, attach_map = dhs_agent.process_tool_call(
            "get_campus_directions", {"destination": "library"}
        )
    assert '"Library"' in result
    assert "campus_map.jpg" in result
    assert attach_map is True


def test_get_campus_directions_uses_static_map_url_without_public_base_url(dhs_agent):
    with patch("app.agent.config.PUBLIC_BASE_URL", ""):
        result, _ = dhs_agent.process_tool_call("get_campus_directions", {"destination": "library"})
    assert "Campus map image: https://raw.githubusercontent.com" in result


def test_get_campus_directions_prefers_same_origin_url_when_public_base_url_set(dhs_agent):
    with patch("app.agent.config.PUBLIC_BASE_URL", "https://chat.dublinusd.org"):
        result, _ = dhs_agent.process_tool_call("get_campus_directions", {"destination": "library"})
    assert "Campus map image: https://chat.dublinusd.org/schools/dhs/campus-map" in result
    assert "raw.githubusercontent.com" not in result


def test_get_club_list_tool_present_when_school_has_clubs_sheet(dhs_agent):
    assert "get_club_list" in [t["name"] for t in dhs_agent.tools]


def test_get_club_list_tool_omitted_when_school_has_no_clubs_sheet(agent):
    assert "get_club_list" not in [t["name"] for t in agent.tools]


def test_get_club_list_cites_the_human_viewable_sheet_not_the_csv_export(dhs_agent):
    with patch("app.agent.get_club_list", return_value="Student Clubs:\n- Chess Club"):
        result, attach_map = dhs_agent.process_tool_call("get_club_list", {})

    assert "SOURCE: https://docs.google.com/spreadsheets/d/" in result
    assert "/edit?gid=" in result
    assert "export?format=csv" not in result
    assert attach_map is False


def test_get_club_list_instructs_model_not_to_claim_current_year(dhs_agent):
    """The club roster is a spreadsheet the club coordinator updates by
    hand, not something tied to the current school year automatically — a
    real case found the sheet was still last year's with no current-year
    tab published yet. The model must not assert/imply the roster is
    confirmed current."""
    with patch("app.agent.get_club_list", return_value="Student Clubs:\n- Chess Club"):
        result, _ = dhs_agent.process_tool_call("get_club_list", {})

    assert "confirmed current" in result.lower()
    assert "previous year" in result.lower()


def test_get_course_catalog_tool_present_when_school_has_catalog(dhs_agent):
    assert "get_course_catalog" in [t["name"] for t in dhs_agent.tools]


def test_get_course_catalog_tool_omitted_for_middle_school(agent):
    """Wells is a middle school — the Grades 9-12 course catalog doesn't
    apply, even though it shares DHS's district_id (and therefore its
    course-catalog data directory)."""
    assert "get_course_catalog" not in [t["name"] for t in agent.tools]


def test_get_course_catalog_department_enum_lists_real_departments(dhs_agent):
    tool = next(t for t in dhs_agent.tools if t["name"] == "get_course_catalog")
    department_schema = tool["input_schema"]["properties"]["department"]
    assert "Engineering" in department_schema["enum"]
    assert "Mathematics" in department_schema["enum"]


def test_get_course_catalog_no_department_returns_overview(dhs_agent):
    with patch("app.agent.get_course_catalog_section", return_value="Graduation requires 230 credits.") as mock_fn:
        result, attach_map = dhs_agent.process_tool_call("get_course_catalog", {})

    mock_fn.assert_called_once_with("dusd", None)
    assert "230 credits" in result
    assert "SOURCE: https://docs.google.com/document/d/1DxIYs_qW9sHB3rNxSrdz8QDy3Vp_lSKUbBSIYrFjigU/edit" in result
    assert attach_map is False


def test_get_course_catalog_source_falls_back_to_website_when_unset():
    """A school with has_course_catalog=True but no course_catalog_url set
    must still cite something usable, not crash or cite 'None'."""
    school = replace(get_school("dhs"), course_catalog_url=None)
    with patch("app.agent.anthropic.Anthropic"):
        agent = SchoolAgent(
            school=school,
            redis_store=RedisStore(client=FakeRedisClient()),
            postgres_store=MagicMock(),
        )

    with patch("app.agent.get_course_catalog_section", return_value="..."):
        result, _ = agent.process_tool_call("get_course_catalog", {})

    assert f"SOURCE: {school.website}" in result


def test_get_course_catalog_result_tells_model_to_preserve_notes(dhs_agent):
    """Course catalog department sections have italicized *NOTE:...* callouts
    that carry the most decision-relevant guidance (e.g. "non-AP Precalculus,
    not AP Precalculus, is the course designed to prepare students for AP
    Calc AB/BC"). Without an explicit instruction, the model tends to
    summarize the section and drop the NOTE, giving a technically-correct
    but critically-incomplete answer. This test guards the instruction that
    keeps it in the reply."""
    fake_section = (
        "**AP Precalculus**\n"
        "Course Number: 797174\n"
        "...\n"
        "*NOTE: It is recommended that students with an interest in taking "
        "AP Calc AB/BC in their mathematics pathway enroll in Precalculus "
        "(non-AP Precalculus) as that is the course designed to prepare "
        "students for success in AP Calc AB/BC.*\n"
    )
    with patch("app.agent.get_course_catalog_section", return_value=fake_section):
        result, _ = dhs_agent.process_tool_call("get_course_catalog", {"department": "Mathematics"})

    # The catalog text itself passes through untouched.
    assert "*NOTE:" in result
    # The appended instruction block tells the model to preserve NOTE callouts
    # and gives it the AP Calc pathway example so the guidance is concrete,
    # not just abstract.
    assert "NOTE" in result and "*NOTE:" in result
    assert "INSTRUCTIONS FOR YOUR RESPONSE" in result
    assert "non-AP Precalculus" in result
    # Counselor-final-say reminder is still there.
    assert "counselor" in result.lower()


def test_get_course_catalog_with_department_passes_it_through(dhs_agent):
    with patch("app.agent.get_course_catalog_section", return_value="PLTW Introduction to Engineering Design...") as mock_fn:
        result, _ = dhs_agent.process_tool_call("get_course_catalog", {"department": "Engineering"})

    mock_fn.assert_called_once_with("dusd", "Engineering")
    assert "PLTW" in result


def test_get_course_catalog_instructs_model_to_recommend_counselor_confirmation(dhs_agent):
    """Course info (prerequisites, credits, availability) can change, and
    only a counselor can confirm what applies to an individual student's
    plan — every catalog answer should nudge toward that, same pattern as
    get_school_information's staff-directory disclaimer."""
    with patch("app.agent.get_course_catalog_section", return_value="..."):
        result, _ = dhs_agent.process_tool_call("get_course_catalog", {})

    assert "counselor" in result.lower()


# ── get_lunch_menu (#68) ────────────────────────────────────────────────────

def test_get_lunch_menu_tool_present_when_school_has_grade_band(dhs_agent):
    assert "get_lunch_menu" in [t["name"] for t in dhs_agent.tools]


def test_get_lunch_menu_tool_present_for_wells_too(agent):
    """Unlike get_course_catalog (high-school only), the lunch menu tool
    applies to both schools — each has its own grade-band data."""
    assert "get_lunch_menu" in [t["name"] for t in agent.tools]


def test_get_lunch_menu_tool_omitted_when_no_grade_band():
    school = replace(get_school("wells"), lunch_menu_grade_band=None)
    with patch("app.agent.anthropic.Anthropic"):
        agent = SchoolAgent(
            school=school,
            redis_store=RedisStore(client=FakeRedisClient()),
            postgres_store=MagicMock(),
        )
    assert "get_lunch_menu" not in [t["name"] for t in agent.tools]


def test_get_lunch_menu_takes_no_parameters(dhs_agent):
    """The whole week is compact enough to return in full every time —
    no sub-topic param for the model to pick wrong and miss info with,
    the failure class hit (and fixed) twice already this session for
    get_school_information and get_course_catalog."""
    tool = next(t for t in dhs_agent.tools if t["name"] == "get_lunch_menu")
    assert tool["input_schema"]["properties"] == {}


def test_get_lunch_menu_calls_service_with_district_and_grade_band(dhs_agent):
    with patch("app.agent.get_lunch_menu_text", return_value="Monday: ...") as mock_fn:
        result, attach_map = dhs_agent.process_tool_call("get_lunch_menu", {})

    mock_fn.assert_called_once_with("dusd", "9-12")
    assert "Monday: ..." in result
    assert attach_map is False


def test_get_lunch_menu_cites_the_served_cycles_own_menu_url(dhs_agent):
    """The cited PDF has to be the one the quoted dishes were parsed from,
    so the cycle's own URL wins over the school-level fallback — otherwise
    an answer quotes this cycle's dishes under last cycle's document."""
    with patch("app.agent.get_lunch_menu_text", return_value="..."), \
            patch("app.agent.get_lunch_menu_urls",
                  return_value=("https://example.test/cycle_menu.pdf", None)):
        result, _ = dhs_agent.process_tool_call("get_lunch_menu", {})

    assert "SOURCE: https://example.test/cycle_menu.pdf" in result


def test_get_lunch_menu_cites_lunch_menu_url_when_cycle_has_none(dhs_agent):
    with patch("app.agent.get_lunch_menu_text", return_value="..."), \
            patch("app.agent.get_lunch_menu_urls", return_value=(None, None)):
        result, _ = dhs_agent.process_tool_call("get_lunch_menu", {})

    assert f"SOURCE: {dhs_agent.school.lunch_menu_url}" in result


def test_get_lunch_menu_mentions_nutrition_url_when_set(dhs_agent):
    """The nutrition PDF (per-ingredient allergen detail) isn't the formal
    SOURCE line — the system prompt only allows one — but should still be
    surfaced as an optional mention for a user who wants to verify allergen
    info themselves."""
    with patch("app.agent.get_lunch_menu_text", return_value="..."), \
            patch("app.agent.get_lunch_menu_urls",
                  return_value=(None, "https://example.test/cycle_nutrition.pdf")):
        result, _ = dhs_agent.process_tool_call("get_lunch_menu", {})

    assert "https://example.test/cycle_nutrition.pdf" in result


def test_get_lunch_menu_mentions_school_nutrition_url_when_cycle_has_none(dhs_agent):
    with patch("app.agent.get_lunch_menu_text", return_value="..."), \
            patch("app.agent.get_lunch_menu_urls", return_value=(None, None)):
        result, _ = dhs_agent.process_tool_call("get_lunch_menu", {})

    assert dhs_agent.school.lunch_menu_nutrition_url in result


def test_get_lunch_menu_source_falls_back_to_website_when_unset():
    """A school with lunch_menu_grade_band set but neither a cycle-level nor
    a school-level menu URL must still cite something usable, not crash or
    cite 'None'."""
    school = replace(get_school("dhs"), lunch_menu_url=None)
    with patch("app.agent.anthropic.Anthropic"):
        agent = SchoolAgent(
            school=school,
            redis_store=RedisStore(client=FakeRedisClient()),
            postgres_store=MagicMock(),
        )

    with patch("app.agent.get_lunch_menu_text", return_value="..."), \
            patch("app.agent.get_lunch_menu_urls", return_value=(None, None)):
        result, _ = agent.process_tool_call("get_lunch_menu", {})

    assert f"SOURCE: {school.website}" in result


def test_get_lunch_menu_instructs_model_to_add_safety_disclaimer(dhs_agent):
    """Never let the model imply a dish is unconditionally "safe" — only
    that a specific allergen isn't listed, with a reminder to confirm
    severe allergies with cafeteria/nutrition staff directly (#68)."""
    with patch("app.agent.get_lunch_menu_text", return_value="..."):
        result, _ = dhs_agent.process_tool_call("get_lunch_menu", {})

    assert "cross-contamination" in result.lower()
    assert "safe" in result.lower()
    assert "cafeteria" in result.lower() or "nutrition staff" in result.lower()


def test_get_no_school_days_cites_the_instructional_calendar_pdf_not_the_events_page(dhs_agent):
    """The no-school-days tool must cite the district's board-approved
    calendar PDF (data/calendars/dusd/2026_27.json's source_url) — not the
    generic events page used for get_calendar_events, which used to be
    reused here and pointed users at the wrong source."""
    result, _ = dhs_agent.process_tool_call("get_no_school_days", {})

    assert "SOURCE: https://drive.google.com/file/d/14AAnvvkvnC8lkoJCbXcr-jwp8t1gci5q/view" in result
    assert "apps/events" not in result


def _system_block(system, marker):
    """The system block containing `marker`. Indexing system[] positionally
    made these tests break whenever a block was added — find by content so
    they assert what they actually care about."""
    matches = [b for b in system if marker in b["text"]]
    assert len(matches) == 1, f"expected exactly one block containing {marker!r}, got {len(matches)}"
    return matches[0]


# ── _call_api passes system as list with cache_control ────────────────────────

def test_call_api_system_is_list_with_cache_control(agent):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}])

    _, kwargs = agent.client.beta.messages.create.call_args
    system = kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
    assert system[0]["text"] == agent._system_prompt
    # Exactly one cached block; every later block is per-request and uncached.
    assert sum("cache_control" in b for b in system) == 1


def test_call_api_puts_cache_breakpoint_on_last_message(agent):
    """Beyond the tools+system prefix (shared across every user of a school),
    the LAST message must also carry a cache_control breakpoint — otherwise a
    tool-calling turn's second (and later) API call reprocesses the entire
    prior conversation at full price instead of reading it from cache."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([
        {"role": "user", "content": "first turn"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second turn"},
    ])

    _, kwargs = agent.client.beta.messages.create.call_args
    messages = kwargs["messages"]
    assert len(messages) == 3
    # Untouched earlier messages keep their original plain-string content —
    # only the last message is transformed.
    assert messages[0]["content"] == "first turn"
    assert messages[1]["content"] == "reply"
    last_content = messages[2]["content"]
    assert last_content == [
        {"type": "text", "text": "second turn", "cache_control": {"type": "ephemeral", "ttl": "5m"}}
    ]


def test_call_api_cache_breakpoint_does_not_mutate_input_messages(agent):
    """_with_cache_breakpoint must return a copy — the caller's `messages`
    list (built from chat()'s local state, not persisted directly) must
    never end up carrying cache_control or content-block-list mutations."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    original = [{"role": "user", "content": "hi"}]
    agent._call_api(original)

    assert original == [{"role": "user", "content": "hi"}]


def test_call_api_cache_breakpoint_on_tool_result_message(agent):
    """The tool-loop's follow-up call appends a user message whose content is
    already a list of tool_result blocks (not a string) — the breakpoint must
    land on the last block in that list without disturbing the others."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    tool_results = [
        {"type": "tool_result", "tool_use_id": "t1", "content": "result one"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "result two"},
    ]
    agent._call_api([{"role": "user", "content": tool_results}])

    _, kwargs = agent.client.beta.messages.create.call_args
    sent_content = kwargs["messages"][0]["content"]
    assert sent_content[0] == {"type": "tool_result", "tool_use_id": "t1", "content": "result one"}
    assert sent_content[1] == {
        "type": "tool_result", "tool_use_id": "t2", "content": "result two",
        "cache_control": {"type": "ephemeral", "ttl": "5m"},
    }


def test_call_api_appends_uncached_datetime_suffix_after_cached_prefix(agent):
    """The current date/time must be appended AFTER the cached prefix, as its
    own block with no cache_control, so per-request date info never busts the
    prompt cache and the cached block stays byte-stable."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    with patch("app.agent.pacific_now") as mock_now:
        import datetime
        from zoneinfo import ZoneInfo
        mock_now.return_value = datetime.datetime(2026, 11, 4, 15, 42, tzinfo=ZoneInfo("America/Los_Angeles"))
        agent._call_api([{"role": "user", "content": "hi"}])

    _, kwargs = agent.client.beta.messages.create.call_args
    system = kwargs["system"]
    suffix = system[1]
    assert "cache_control" not in suffix
    assert suffix["type"] == "text"
    assert "Current date/time:" in suffix["text"]
    assert "2026-11-04" in suffix["text"]
    assert "America/Los_Angeles" in suffix["text"]
    assert "School year: 2026-2027" in suffix["text"]


def test_datetime_suffix_recomputed_on_every_call(agent):
    """Unlike the cached system prompt (built once at construction), the date
    suffix must be freshly computed on every _call_api invocation so a long
    conversation doesn't drift onto a stale date."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    import datetime
    from zoneinfo import ZoneInfo
    with patch("app.agent.pacific_now") as mock_now:
        mock_now.return_value = datetime.datetime(2026, 11, 4, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        agent._call_api([{"role": "user", "content": "hi"}])
        first_suffix = agent.client.beta.messages.create.call_args[1]["system"][1]["text"]

        mock_now.return_value = datetime.datetime(2026, 11, 5, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        agent._call_api([{"role": "user", "content": "hi again"}])
        second_suffix = agent.client.beta.messages.create.call_args[1]["system"][1]["text"]

    assert first_suffix != second_suffix
    assert "2026-11-04" in first_suffix
    assert "2026-11-05" in second_suffix


def test_call_api_uses_beta_namespace_without_a_stale_betas_flag(agent):
    """Prompt caching is GA and needs no beta header — client.beta.messages.create
    is still used (in case a future feature needs the namespace), but the old
    2024 prompt-caching beta flag must not be sent."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}])

    agent.client.beta.messages.create.assert_called_once()
    agent.client.messages.create.assert_not_called()

    _, kwargs = agent.client.beta.messages.create.call_args
    assert "betas" not in kwargs


# ── Conversation-truncated notice (#history-cap) ────────────────────────────

def test_call_api_omits_truncation_notice_by_default(agent):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}])

    _, kwargs = agent.client.beta.messages.create.call_args
    assert not [b for b in kwargs["system"]
                if "only retain the most recent conversation" in b["text"]]


def test_call_api_adds_truncation_notice_when_flagged(agent):
    from app.store.redis_store import MAX_HISTORY

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}], conversation_truncated=True)

    _, kwargs = agent.client.beta.messages.create.call_args
    system = kwargs["system"]
    block = _system_block(system, "only retain the most recent conversation")
    assert "cache_control" not in block
    assert str(MAX_HISTORY) in block["text"]


def test_chat_tells_model_when_conversation_was_truncated(agent):
    """End-to-end: once a session has appended more than MAX_HISTORY
    messages, chat() must pass the truncation notice through to _call_api
    without the caller having to know about it."""
    from app.store.redis_store import MAX_HISTORY

    key = agent._session_key("truncated_user")
    for i in range(MAX_HISTORY + 1):
        agent.redis_store.append_message(key, {"role": "user", "content": str(i)})

    agent.client.beta.messages.create.return_value = _text_response("answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""):
        agent.chat("did I ask about something last week?", user_id="truncated_user")

    _, kwargs = agent.client.beta.messages.create.call_args
    system = kwargs["system"]
    assert str(MAX_HISTORY) in _system_block(
        system, "only retain the most recent conversation")["text"]


def test_chat_omits_truncation_notice_for_short_conversation(agent):
    agent.client.beta.messages.create.return_value = _text_response("answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""):
        agent.chat("hi", user_id="fresh_user")

    _, kwargs = agent.client.beta.messages.create.call_args
    assert not [b for b in kwargs["system"]
                if "only retain the most recent conversation" in b["text"]]


# ── Last tool has cache_control ───────────────────────────────────────────────

def test_last_tool_has_cache_control(agent):
    last_tool = agent.tools[-1]
    assert last_tool.get("cache_control") == {"type": "ephemeral", "ttl": "5m"}


def test_non_last_tools_have_no_cache_control(agent):
    for tool in agent.tools[:-1]:
        assert "cache_control" not in tool


def test_last_tool_has_cache_control_for_dhs(dhs_agent):
    """The cache_control breakpoint must land on whichever tool ends up last
    (get_lunch_menu, for DHS), regardless of which optional tools —
    campus directions, club roster, course catalog, lunch menu — a given
    school has registered."""
    last_tool = dhs_agent.tools[-1]
    assert last_tool["name"] == "get_lunch_menu"
    assert last_tool.get("cache_control") == {"type": "ephemeral", "ttl": "5m"}


def test_last_tool_has_cache_control_without_campus_map(agent_without_campus_map):
    last_tool = agent_without_campus_map.tools[-1]
    assert last_tool["name"] == "get_lunch_menu"
    assert last_tool.get("cache_control") == {"type": "ephemeral", "ttl": "5m"}


# ── Dynamic context injected into first user message only ─────────────────────

def test_dynamic_context_prepended_to_first_message(agent):
    agent.client.beta.messages.create.return_value = _text_response("Test response")

    with patch("app.agent.get_school_day_status", return_value="Regular school day"), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("What time does school start?", user_id="test_user")

    _, kwargs = agent.client.beta.messages.create.call_args
    first_message = kwargs["messages"][0]
    assert first_message["role"] == "user"
    # content is a content-block list (not a bare string) — _call_api wraps
    # the last message with a cache_control breakpoint before sending.
    first_message_text = first_message["content"][0]["text"]
    assert first_message_text.startswith("[Context:")
    assert "What time does school start?" in first_message_text


def test_dynamic_context_not_stored_in_history(agent):
    agent.client.beta.messages.create.return_value = _text_response("Test response")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="test_user2")

    stored = agent.redis_store.get_conversation(agent._session_key("test_user2"))
    assert stored[0]["content"] == "Hello"


def test_dynamic_context_not_prepended_on_subsequent_turns(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("First question", user_id="u3")
        agent.chat("Second question", user_id="u3")

    last_call_messages = agent.client.beta.messages.create.call_args_list[-1][1]["messages"]
    second_user_message = [m for m in last_call_messages if m["role"] == "user"][1]
    assert not second_user_message["content"][0]["text"].startswith("[Context:")


# ── State now lives in the injected RedisStore, not on the agent instance ─────

def test_agent_has_no_instance_state_dicts(agent):
    for attr in ("conversations", "feedback_asked", "feedback_pending",
                 "last_responses", "attach_map"):
        assert not hasattr(agent, attr)


def test_chat_returns_chat_reply(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        reply = agent.chat("Hello", user_id="u4")

    assert isinstance(reply, agent_module.ChatReply)
    assert "Answer" in reply.text
    assert reply.attach_map is False


def test_attach_map_true_when_campus_directions_tool_used(agent):
    tool_use_block = MagicMock(type="tool_use", name="get_campus_directions",
                                input={"destination": "library"}, id="tool_1")
    tool_use_block.name = "get_campus_directions"
    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]

    agent.client.beta.messages.create.side_effect = [tool_response, _text_response("Here's the map")]

    with patch.object(agent, "process_tool_call", return_value=("map info", True)), \
         patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        reply = agent.chat("Where is the library?", user_id="u5")

    assert reply.attach_map is True


# ── No dangling history entry when the API call fails ──────────────────────────

def test_no_dangling_history_entry_on_api_exception(agent):
    agent.client.beta.messages.create.side_effect = Exception("boom")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        # agent.chat now lets upstream failures propagate so the /chat
        # endpoint can return HTTP 500 (proper observability signal).
        with pytest.raises(Exception, match="boom"):
            agent.chat("Hello", user_id="u6")

    # The real invariant this test protects: even when the API call fails,
    # we must not have left a partial user message in the persisted history.
    assert agent.redis_store.get_conversation(agent._session_key("u6")) == []


# ── Clear-conversation command (#72) ────────────────────────────────────────

def test_clear_command_wipes_conversation_and_confirms(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")
    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="u_clear")

    assert agent.redis_store.get_conversation(agent._session_key("u_clear")) != []

    reply = agent.chat("clear", user_id="u_clear")

    assert reply.text == "Context cleared for Wells Middle School. What can I help you with?"
    assert agent.redis_store.get_conversation(agent._session_key("u_clear")) == []


@pytest.mark.parametrize("trigger", ["clear", "CLEAR", "Clear", "/clear", "/CLEAR", "  clear  "])
def test_clear_command_is_case_insensitive_and_trims_whitespace(agent, trigger):
    reply = agent.chat(trigger, user_id="u_clear2")
    assert reply.text == "Context cleared for Wells Middle School. What can I help you with?"


def test_clear_confirmation_names_the_pinned_school(dhs_agent):
    """Two schools' widgets share one origin and can share a session cookie
    (see _session_key's docstring) — the confirmation must name the school
    whose conversation actually got cleared, not a generic message that could
    read as ambiguous when a browser has chatted with both."""
    reply = dhs_agent.chat("clear", user_id="u_clear_dhs")
    assert reply.text == "Context cleared for Dublin High School. What can I help you with?"


# ── /help reflects each school's actual registered tools ────────────────────

def test_help_command_lists_only_this_schools_actual_capabilities(agent):
    """Wells has no clubs_sheet_url or has_course_catalog — /help must not
    claim capabilities this school doesn't actually have. Wells' own
    sitemap-discovery pass (#117) DID populate athletics/family/enrollment/
    technology, and its own lunch-menu grade band (#68), so those are
    asserted present, not absent."""
    reply = agent.chat("help", user_id="u_help_wells")

    assert "Bell schedule" in reply.text
    assert "Course catalog" not in reply.text
    assert "Club schedules" not in reply.text
    assert "Sports registration" in reply.text
    assert "enrollment" in reply.text
    assert "Student Google account" in reply.text
    assert "Lunch menu" in reply.text


def test_help_command_lists_dhs_full_capabilities(dhs_agent):
    reply = dhs_agent.chat("/help", user_id="u_help_dhs")

    assert "Campus directions" in reply.text
    assert "Club schedules" in reply.text
    assert "Course catalog" in reply.text
    assert "Sports registration" in reply.text
    assert "enrollment" in reply.text
    assert "Student Google account" in reply.text
    assert "Lunch menu" in reply.text


def test_help_command_mentions_announcements_button(agent):
    reply = agent.chat("help", user_id="u_help_announce")
    assert "announcements button" in reply.text


# ── /report command redirects to the help-popover form ─────────────────────

@pytest.mark.parametrize("trigger", ["report", "REPORT", "Report", "/report", "/REPORT", "  report  "])
def test_report_command_points_to_the_help_popover(agent, trigger):
    """/report used to be a real in-chat command before it was replaced by
    the help-popover form (#cost-estimate) — without special-casing it, the
    model has no way to know that popover exists (it's UI-only, never
    mentioned in the system prompt) and would just deflect to 'call the
    school' instead of the actual, better path."""
    reply = agent.chat(trigger, user_id="u_report")

    assert "Report a problem or idea" in reply.text
    assert "help button" in reply.text
    assert reply.attach_map is False


def test_report_command_does_not_call_the_api(agent):
    reply = agent.chat("/report", user_id="u_report2")

    agent.client.beta.messages.create.assert_not_called()
    assert "help button" in reply.text


def test_clear_command_resets_feedback_state_too(agent):
    key = agent._session_key("u_clear3")
    agent.redis_store.mark_feedback_asked(key)
    agent.redis_store.mark_feedback_pending(key)

    agent.chat("clear", user_id="u_clear3")

    assert agent.redis_store.is_feedback_asked(key) is False
    assert agent.redis_store.is_feedback_pending(key) is False


def test_next_message_after_clear_has_no_prior_history(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")
    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("First question", user_id="u_clear4")
        agent.chat("clear", user_id="u_clear4")
        agent.chat("Second question", user_id="u_clear4")

    last_call_messages = agent.client.beta.messages.create.call_args_list[-1][1]["messages"]
    # Only the fresh post-clear turn is present — no bleed-through from the
    # conversation that existed before "clear" wiped it.
    assert len(last_call_messages) == 1
    last_message_text = last_call_messages[0]["content"][0]["text"]
    assert "First question" not in last_message_text
    assert "Second question" in last_message_text


# ── Feedback flow routes through the injected RedisStore ───────────────────────

def test_feedback_ask_suffix_added_once_per_session(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        first = agent.chat("Hello", user_id="u7")

    assert "Was this helpful?" in first.text
    assert agent.redis_store.is_feedback_asked(agent._session_key("u7")) is True
    assert agent.redis_store.is_feedback_pending(agent._session_key("u7")) is True


def test_passive_feedback_reply_records_and_acknowledges(agent):
    agent.redis_store.mark_feedback_pending(agent._session_key("u8"))

    reply = agent.chat("1", user_id="u8")

    assert "Thanks for the feedback" in reply.text
    assert agent.redis_store.is_feedback_pending(agent._session_key("u8")) is False
    agent.postgres_store.record_feedback.assert_called_once()
    _, kwargs = agent.postgres_store.record_feedback.call_args
    assert kwargs["sentiment"] == "positive"
    assert kwargs["feedback_type"] == "passive"
    assert kwargs["school_id"] == "wells"


def test_record_thanks_records_positive_feedback(agent):
    agent.record_thanks(user_id="u9")

    agent.postgres_store.record_feedback.assert_called_once()
    _, kwargs = agent.postgres_store.record_feedback.call_args
    assert kwargs["feedback_type"] == "thanks"
    assert kwargs["sentiment"] == "positive"
    assert kwargs["school_id"] == "wells"


def test_record_report_persists_name_email_and_message(agent):
    agent.redis_store.set_last_response(agent._session_key("u10"), "previous answer")

    agent.record_report(
        user_id="u10", name="Jamie", email="jamie@example.com",
        message="the phone number was wrong",
    )

    agent.postgres_store.record_feedback.assert_called_once()
    _, kwargs = agent.postgres_store.record_feedback.call_args
    assert kwargs["feedback_type"] == "report"
    assert kwargs["sentiment"] == "negative"
    assert kwargs["name"] == "Jamie"
    assert kwargs["email"] == "jamie@example.com"
    assert kwargs["raw"] == "the phone number was wrong"
    assert kwargs["last_response"] == "previous answer"


def test_record_report_feature_idea_uses_distinct_type_and_sentiment(agent):
    """report_type='feature' must be filterable in Postgres as its own
    feedback.type, distinct from a problem report — and 'positive' sentiment
    since a feature idea isn't a complaint."""
    agent.record_report(
        user_id="u10b", name="Jamie", email="jamie@example.com",
        message="could you add a lunch menu lookup?", report_type="feature",
    )

    _, kwargs = agent.postgres_store.record_feedback.call_args
    assert kwargs["feedback_type"] == "feature_request"
    assert kwargs["sentiment"] == "positive"


def test_record_report_propagates_postgres_failures(agent):
    """Unlike passive/thanks feedback, report submission failures must NOT be
    swallowed — the /feedback/report endpoint needs to see the exception so it
    can return a 5xx instead of falsely confirming the report was saved."""
    agent.postgres_store.record_feedback.side_effect = Exception("db down")

    with pytest.raises(Exception, match="db down"):
        agent.record_report(user_id="u11", name="Jamie", email="jamie@example.com", message="broken")


def test_system_prompt_instructs_scraped_content_is_untrusted(agent):
    prompt = agent._system_prompt
    assert "<scraped_page>" in prompt
    assert "untrusted" in prompt.lower()


def test_clear_conversation_clears_redis_session(agent):
    agent.redis_store.append_message(agent._session_key("u11"), {"role": "user", "content": "hi"})
    agent.redis_store.mark_feedback_asked(agent._session_key("u11"))

    agent.clear_conversation("u11")

    assert agent.redis_store.get_conversation(agent._session_key("u11")) == []
    assert agent.redis_store.is_feedback_asked(agent._session_key("u11")) is False


# ── Restore chat history on reopen (#73) ────────────────────────────────────

def test_get_history_empty_for_fresh_session(agent):
    assert agent.get_history("never_chatted") == []


def test_get_history_returns_messages_oldest_first(agent):
    key = agent._session_key("u12")
    agent.redis_store.append_message(key, {"role": "user", "content": "hi"})
    agent.redis_store.append_message(key, {"role": "assistant", "content": "hello!"})

    history = agent.get_history("u12")

    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ]


def test_get_history_respects_limit():
    """Only the most recent `limit` messages, not the oldest."""
    with patch("app.agent.anthropic.Anthropic"):
        redis_store = RedisStore(client=FakeRedisClient())
        agent_ = SchoolAgent(school=get_school("wells"), redis_store=redis_store, postgres_store=MagicMock())
    key = agent_._session_key("u13")
    for i in range(5):
        redis_store.append_message(key, {"role": "user", "content": str(i)})

    assert agent_.get_history("u13", limit=2) == [
        {"role": "user", "content": "3"},
        {"role": "user", "content": "4"},
    ]


def test_get_history_empty_after_clear(agent):
    key = agent._session_key("u14")
    agent.redis_store.append_message(key, {"role": "user", "content": "hi"})

    agent.clear_conversation("u14")

    assert agent.get_history("u14") == []


def test_get_history_scoped_per_school():
    """Same user_id, different schools, SAME underlying Redis — history must
    not bleed across (same reasoning as _session_key's school-scoping for
    feedback: a browser could present the same session cookie to both)."""
    with patch("app.agent.anthropic.Anthropic"):
        shared_redis_store = RedisStore(client=FakeRedisClient())
        wells_agent = SchoolAgent(school=get_school("wells"), redis_store=shared_redis_store, postgres_store=MagicMock())
        dhs_agent = SchoolAgent(school=get_school("dhs"), redis_store=shared_redis_store, postgres_store=MagicMock())

    shared_redis_store.append_message(
        wells_agent._session_key("shared_user"), {"role": "user", "content": "wells message"}
    )

    assert wells_agent.get_history("shared_user") == [{"role": "user", "content": "wells message"}]
    assert dhs_agent.get_history("shared_user") == []


# ── Redis keys are scoped per school ────────────────────────────────────────────

# ── Language preference / directive (#62) ──────────────────────────────────

def test_language_directive_suffix_mirrors_user_language_with_english_fallback(agent):
    """English (the toggle default) is no longer a special no-directive
    case — the directive is always present, since it primarily mirrors
    whatever language the user's own message is in; the toggle only
    supplies the fallback for ambiguous messages."""
    suffix = agent._language_directive_suffix("en")
    assert "same language as the user's current message" in suffix
    assert "default to English" in suffix


def test_language_directive_suffix_falls_back_to_english_for_unknown_language(agent):
    """An unrecognized code (e.g. a stale client) falls back to English
    rather than raising or omitting the directive."""
    suffix = agent._language_directive_suffix("fr")
    assert "default to English" in suffix


def test_language_directive_suffix_for_spanish(agent):
    suffix = agent._language_directive_suffix("es")
    assert suffix == (
        "Always respond in the same language as the user's current message, "
        "regardless of the language of tool output or scraped content. If "
        "the message doesn't clearly indicate a language, default to Spanish."
    )


def test_language_directive_suffix_for_mandarin(agent):
    suffix = agent._language_directive_suffix("zh")
    assert "Mandarin Chinese" in suffix
    assert "regardless of the language of tool output or scraped content" in suffix


def test_language_directive_suffix_for_traditional_mandarin(agent):
    suffix = agent._language_directive_suffix("zh-Hant")
    assert "Traditional Mandarin Chinese" in suffix
    assert "regardless of the language of tool output or scraped content" in suffix


def test_call_api_always_includes_a_third_uncached_language_block(agent):
    """The language directive is always present now (it mirrors the user's
    message, not just the toggle), so even a call with no language
    specified gets a third, uncached block."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}])

    system = agent.client.beta.messages.create.call_args[1]["system"]
    block = _system_block(system, "default to English")
    assert "cache_control" not in block


def test_call_api_appends_uncached_language_suffix_for_spanish(agent):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}], language="es")

    system = agent.client.beta.messages.create.call_args[1]["system"]
    language_block = _system_block(system, "default to")
    assert "cache_control" not in language_block
    assert language_block["type"] == "text"
    assert "default to Spanish" in language_block["text"]


def test_call_api_appends_uncached_language_suffix_for_mandarin(agent):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}], language="zh")

    system = agent.client.beta.messages.create.call_args[1]["system"]
    _system_block(system, "default to Simplified Mandarin Chinese")


def test_chat_defaults_to_english_when_no_language_ever_set(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="lang_u1")

    system = agent.client.beta.messages.create.call_args[1]["system"]
    _system_block(system, "default to English")


def test_chat_with_language_arg_persists_and_applies_directive(agent):
    agent.client.beta.messages.create.return_value = _text_response("Hola")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hola", user_id="lang_u2", language="es")

    system = agent.client.beta.messages.create.call_args[1]["system"]
    assert "default to Spanish" in system[2]["text"]
    assert agent.redis_store.get_preferred_language(agent._session_key("lang_u2")) == "es"


def test_chat_reuses_persisted_language_on_later_turns_without_explicit_arg(agent):
    """The core multi-turn requirement: once a language is chosen, later
    /chat calls that don't repeat it (e.g. an older client) must still get
    the directive from what was persisted for this session."""
    agent.client.beta.messages.create.return_value = _text_response("Ni hao")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("First", user_id="lang_u3", language="zh")
        agent.chat("Second", user_id="lang_u3")  # no language kwarg this time

    last_system = agent.client.beta.messages.create.call_args_list[-1][1]["system"]
    assert "default to Simplified Mandarin Chinese" in last_system[2]["text"]


def test_chat_language_survives_clear_conversation(agent):
    """clear_conversation resets history/feedback state, not the user's
    language preference — same reasoning as the session_id itself surviving
    a clear."""
    agent.client.beta.messages.create.return_value = _text_response("Hola")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hola", user_id="lang_u4", language="es")

    agent.clear_conversation("lang_u4")

    assert agent.redis_store.get_preferred_language(agent._session_key("lang_u4")) == "es"


def test_chat_ignores_unknown_language_code(agent):
    """An unrecognized language value (e.g. a stale client) must not persist
    garbage or blow up the request — falls back to whatever's stored, or
    English."""
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="lang_u5", language="fr")

    system = agent.client.beta.messages.create.call_args[1]["system"]
    _system_block(system, "default to English")
    assert agent.redis_store.get_preferred_language(agent._session_key("lang_u5")) is None


def test_system_prompt_includes_translated_useful_links_for_wells(agent):
    """Translated useful-links labels (#62) live in the cached prefix itself,
    alongside the English list — see _build_system_prompt's docstring on why
    that's safe for caching."""
    prompt = agent._system_prompt
    assert "Spanish labels" in prompt
    assert "Mandarin Chinese labels" in prompt
    assert "Portal para padres" in prompt
    assert "家长门户网站" in prompt


def test_conversations_are_isolated_across_schools(agent, dhs_agent):
    """Two schools' agents share the same underlying Redis client (as they do
    in production). The same raw user_id — e.g. a reused signed session cookie
    presented to both schools' widgets — must not leak conversation state
    between them."""
    shared_client = agent.redis_store.client
    dhs_agent.redis_store = RedisStore(client=shared_client)

    agent.redis_store.append_message(agent._session_key("shared-session"), {"role": "user", "content": "wells message"})
    dhs_agent.redis_store.append_message(dhs_agent._session_key("shared-session"), {"role": "user", "content": "dhs message"})

    wells_history = agent.redis_store.get_conversation(agent._session_key("shared-session"))
    dhs_history = dhs_agent.redis_store.get_conversation(dhs_agent._session_key("shared-session"))

    assert wells_history == [{"role": "user", "content": "wells message"}]
    assert dhs_history == [{"role": "user", "content": "dhs message"}]


# ── nutrition documents in per-request system context (#159) ───────────────

def test_call_api_states_the_nutrition_documents_every_request(agent):
    """These must NOT live only in the lunch tool's result. A tool result is
    discarded at the end of its turn, and "what is the nutrition info" is
    almost always a follow-up to a menu question — so the tool result is the
    one place the model is least likely to see this link. Measured at 0/5 on
    that two-turn sequence before this block existed."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}])

    system = agent.client.beta.messages.create.call_args[1]["system"]
    block = _system_block(system, "SCHOOL MEAL NUTRITION DOCUMENTS")
    assert "nutriinfo" in block["text"]
    # Per-request, so it must not be inside the cached prefix — it changes at
    # every menu-cycle rollover.
    assert "cache_control" not in block


def test_nutrition_suffix_forbids_quoting_figures_from_the_documents(agent):
    """The menu tool returns allergens only, and the PDFs' figures are
    per-ingredient rather than per-serving totals — summing them yields a
    garden salad at 863 kcal. Linking is safe; quoting is not."""
    suffix = agent._lunch_nutrition_suffix()

    assert "never quote or estimate a figure" in suffix
    assert "per-serving" in suffix


def test_nutrition_suffix_forbids_deflecting_to_the_school(agent):
    """The bug: it answered "nutrition information is unavailable, call the
    school" while holding the district's own figures."""
    suffix = agent._lunch_nutrition_suffix()

    assert "do NOT tell them to phone the school" in suffix.replace("\n", " ")
    assert "nutrition information is unavailable" in suffix.replace("\n", " ")


def test_nutrition_suffix_lists_the_upcoming_period_too(agent):
    """Nutrition documents are period-specific, so a question about a date in
    the next period needs that period's document, not the current one's."""
    suffix = agent._lunch_nutrition_suffix()

    assert suffix.count("nutriinfo") >= 2


def test_nutrition_suffix_absent_for_a_school_with_no_lunch_menu():
    school = replace(get_school("wells"), lunch_menu_grade_band=None)
    with patch("app.agent.anthropic.Anthropic"):
        agent = SchoolAgent(
            school=school,
            redis_store=RedisStore(client=FakeRedisClient()),
            postgres_store=MagicMock(),
        )

    assert agent._lunch_nutrition_suffix() is None


def test_nutrition_suffix_falls_back_to_the_school_record_url(agent):
    """A school whose cycle files predate nutrition_url still gets a link."""
    with patch("app.agent.get_lunch_nutrition_links", return_value=[]):
        suffix = agent._lunch_nutrition_suffix()

    assert agent.school.lunch_menu_nutrition_url in suffix
