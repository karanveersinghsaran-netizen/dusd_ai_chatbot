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
                    "academics, clubs, sports, contact info, and announcements. "
                    "Use the 'page_group' parameter to target specific sections: "
                    "'principal' for principal/assistant principal/admin info, "
                    "'staff' for the full staff directory (teachers, counselors, support staff), "
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
                            "enum": ["home", "principal", "staff"],
                            "description": (
                                "Which page group to scrape. "
                                "'principal' for questions about the principal or assistant principals. "
                                "'staff' for questions about teachers, counselors, or any staff member by name/department. "
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

CRITICAL RULES:
- NEVER guess, assume, or fabricate school information
- ALWAYS call a tool before answering any factual question about the school — including follow-up questions. Do not rely on prior tool results already in the conversation; call the tool again.
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
