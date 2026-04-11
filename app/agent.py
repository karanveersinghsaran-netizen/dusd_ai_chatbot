import anthropic
import re
import time
from datetime import date
from typing import Dict, Any

from app import config
from app.services.scraper import scraper
from app.services.calendar import (
    get_upcoming_events,
    get_upcoming_no_school_days,
    get_school_day_status,
    get_today_status,
)


class WellsMiddleSchoolAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = "claude-haiku-4-5-20251001"
        self.conversations = {}

        self.tools = [
            {
                "name": "get_school_information",
                "description": (
                    "Get information about Wells Middle School from the school website. "
                    "Use this to answer questions about the school such as: staff, programs, "
                    "academics, clubs, contact info, and announcements. "
                    "Use the 'page_group' parameter to target specific sections: "
                    "'principal' for principal/assistant principal/admin info, "
                    "'staff' for the full staff directory (teachers, counselors, support staff), "
                    "'academics' for dress code, academic programs, homework policy, after-school hours, "
                    "'counseling' for counselor names, emails, and office locations, "
                    "'attendance' for attendance policies and absence reporting, "
                    "'clubs' for student clubs and organizations, "
                    "'home' for general school info (default)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's question about the school"
                        },
                        "page_group": {
                            "type": "string",
                            "enum": ["home", "principal", "staff", "academics", "counseling", "attendance", "clubs"],
                            "description": (
                                "Which page group to scrape. "
                                "'principal' for questions about the principal or assistant principals. "
                                "'staff' for questions about teachers or any staff member by name/department. "
                                "'academics' for dress code, academic programs, homework policy, after-school programs. "
                                "'counseling' for counselor names, emails, office locations, or counseling services. "
                                "'attendance' for attendance policies and how to report absences. "
                                "'clubs' for student clubs, organizations, and activities. "
                                "Defaults to 'home'."
                            )
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_calendar_events",
                "description": (
                    "Get upcoming events and dates from the Wells Middle School calendar. "
                    "Use this for questions about events, schedules, dates, or upcoming activities."
                ),
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "get_no_school_days",
                "description": (
                    "Get upcoming no-school days, holidays, and breaks from the DUSD "
                    "instructional calendar. Use this for questions about days off, holidays, or breaks."
                ),
                "input_schema": {"type": "object", "properties": {}}
            }
        ]

        self._system_prompt_template = """You are a helpful assistant for Wells Middle School, part of the Dublin Unified School District in Dublin, California.

Today's date is {today}.

You help students, parents, and staff with questions about the school — including academics, staff, events, clubs, sports, schedules, and general information.

SCHOOL INFORMATION:
Name: Wells Middle School
Address: 6800 Penn Drive, Dublin, CA 94568
Phone: (925) 828-6227
Fax: (925) 829-8851
Office Hours: Monday–Friday, 8:00 AM – 4:00 PM
Website: https://wms.dublinusd.org/
District: Dublin Unified School District

BELL SCHEDULE (2025-26):
Monday / Tuesday / Thursday / Friday:
  Period 0:  7:40 AM – 8:30 AM
  Period 1:  8:35 AM – 9:25 AM
  Period 2:  9:29 AM – 10:19 AM
  Break:     10:19 AM – 10:26 AM
  AVID/Advisory: 10:30 AM – 10:55 AM
  Period 3:  10:59 AM – 11:49 AM
  Lunch A:   11:49 AM – 12:23 PM
  Period 4 (Lunch A): 12:27 PM – 1:17 PM
  Period 4 (Lunch B): 11:53 AM – 12:43 PM
  Lunch B:   12:43 PM – 1:17 PM
  Period 5:  1:21 PM – 2:11 PM
  Period 6:  2:15 PM – 3:05 PM

Wednesday:
  Period 0:  7:45 AM – 8:30 AM
  Period 1:  8:35 AM – 9:23 AM
  Period 2:  9:27 AM – 10:10 AM
  Break:     10:10 AM – 10:17 AM
  Period 3:  10:21 AM – 11:04 AM
  Lunch A:   11:04 AM – 11:39 AM
  Period 4 (Lunch A): 11:43 AM – 12:26 PM
  Period 4 (Lunch B): 11:08 AM – 11:51 AM
  Lunch B:   11:51 AM – 12:26 PM
  Period 5:  12:30 PM – 1:13 PM
  Period 6:  1:17 PM – 2:00 PM

Minimum Days:
  Period 0:  8:05 AM – 8:30 AM
  Period 1:  8:35 AM – 9:07 AM
  Period 2:  9:11 AM – 9:41 AM
  Period 3:  9:45 AM – 10:15 AM
  Period 4:  10:22 AM – 10:52 AM
  Period 5:  10:56 AM – 11:26 AM
  Period 6:  11:30 AM – 12:00 PM (Lunch Grab & Go)

USEFUL LINKS (share these when relevant):
- Bell Schedule PDF: https://drive.google.com/file/d/107PmZjvXZacDQgX_O6mpDd-09qWPgiIi/view
- Athletics: https://sites.google.com/dublinusd.org/wmsathletics/home
- AVID Program: https://sites.google.com/dublinusd.org/wells-middle-school-avid
- Parent Portal (grades/attendance): https://icampus.dublinusd.org/campus/portal/dublin.jsp
- Counseling Appointment Request: https://forms.gle/dXkFqP5bRxUGtFvi9
- FlexiSched (counseling schedule): https://wells.flexisched.net/
- Wells Webstore: https://wellswebstore.myschoolcentral.com
- Elective Handbook: https://drive.google.com/file/d/1uVqHtEqBH17XAKrkz9lu3OStBcIMVQ9G/view
- Bullying Report Form: https://forms.gle/7xYV7TgBdpbYA8z87

CRITICAL RULES:
- NEVER guess, assume, or fabricate school information
- ALWAYS call a tool before answering any factual question about the school — including follow-up questions. Do not rely on prior tool results already in the conversation; call the tool again.
- Bell schedule and useful links above are hardcoded facts — you may answer those directly without calling a tool.
- If you cannot find an answer from the tools, say so clearly and suggest contacting the school directly
- Be friendly, concise, and helpful"""

    # Page URL registry — add new URLs here as they become available
    PAGES = {
        "home": [
            "/",
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449301&type=d&termREC_ID=&pREC_ID=921000",
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449301&type=d&termREC_ID=&pREC_ID=1132073",
        ],
        "principal": [
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449301&type=d&termREC_ID=&pREC_ID=921000",
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449301&type=d&termREC_ID=&pREC_ID=1132073",
        ],
        "staff": [
            "https://wms.dublinusd.org/apps/staff/",
        ],
        "academics": [
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449299&type=d",   # About our School
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449323&type=d",   # Academic Opportunities
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449318&type=d",   # Homework Policy
        ],
        "counseling": [
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449306&type=d",   # Counseling Staff
        ],
        "attendance": [
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449304&type=d",   # Attendance
        ],
        "clubs": [
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449324&type=d",   # Student Clubs & Organizations
            "https://wms.dublinusd.org/apps/pages/index.jsp?uREC_ID=449323&type=d",   # Academic Opportunities (lists programs)
        ],
    }

    @property
    def system_prompt(self) -> str:
        today = date.today()
        school_status = get_school_day_status(today)
        event_status = get_today_status()
        extra = f"\nSCHOOL STATUS: {school_status}" if school_status else ""
        if event_status:
            extra += f"\n{event_status}"
        return self._system_prompt_template.format(today=today.strftime("%A, %B %d, %Y")) + extra

    def process_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        if tool_name == "get_school_information":
            page_group = tool_input.get("page_group", "home")
            pages = self.PAGES.get(page_group, self.PAGES["home"])
            result = scraper.get_school_info(pages)
            if page_group == "staff":
                result += "\n\n[NOTE: Please include a brief disclaimer in your response that the staff directory may not always be up to date, and users should contact the school directly at (925) 828-6227 to confirm current staff assignments.]"
            return result
        if tool_name == "get_calendar_events":
            return get_upcoming_events()
        if tool_name == "get_no_school_days":
            return get_upcoming_no_school_days()
        return "Tool not found"

    def clear_conversation(self, user_id: str = "default"):
        self.conversations.pop(user_id, None)

    def _call_api(self, messages: list, retries: int = 3) -> Any:
        """Call Claude API with exponential backoff for transient errors."""
        for attempt in range(retries):
            try:
                return self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    tools=self.tools,
                    messages=messages
                )
            except (anthropic.RateLimitError, anthropic.InternalServerError):
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def chat(self, user_message: str, user_id: str = "default") -> str:
        try:
            # Basic content filter
            for word in ['fuck', 'shit', 'bitch', 'bastard']:
                if re.search(r'\b' + re.escape(word) + r'\b', user_message.lower()):
                    return ("I'm sorry, but I can only respond to respectful inquiries. "
                            "Please keep communication kind and respectful.")

            if user_id not in self.conversations:
                self.conversations[user_id] = []

            self.conversations[user_id].append({"role": "user", "content": user_message})
            messages = self.conversations[user_id].copy()
            response = self._call_api(messages)

            # Agentic loop — process ALL tool_use blocks before next API call
            while response.stop_reason == "tool_use":
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    break

                tool_results = []
                for block in tool_use_blocks:
                    try:
                        result = self.process_tool_call(block.name, block.input)
                    except Exception as e:
                        result = f"Tool error: {str(e)}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                response = self._call_api(messages)

            final_response = "".join(
                block.text for block in response.content if hasattr(block, "text")
            ) or "I'm not sure how to help with that. Please contact Wells Middle School directly."

            self.conversations[user_id].append({"role": "assistant", "content": final_response})

            # Keep last 20 messages
            if len(self.conversations[user_id]) > 20:
                self.conversations[user_id] = self.conversations[user_id][-20:]

            return final_response

        except Exception as e:
            # Roll back the user message to keep history clean
            if self.conversations.get(user_id) and \
               self.conversations[user_id][-1].get("content") == user_message:
                self.conversations[user_id].pop()
            return f"Sorry, I encountered an error: {str(e)}"


agent = WellsMiddleSchoolAgent()


if __name__ == "__main__":
    print("Wells Middle School AI Chatbot")
    print("Type 'quit' to exit, 'clear' to reset conversation.\n")
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        if user_input.lower() == "clear":
            agent.clear_conversation()
            print("Conversation cleared.\n")
            continue
        print(f"\nBot: {agent.chat(user_input)}\n")
