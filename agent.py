import anthropic
import re
from typing import Dict, Any
import config
from website_scraper import scraper


class WellsMiddleSchoolAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = "claude-haiku-4-5-20251001"

        # Store conversation history per user (using phone number as key)
        self.conversations = {}

        self.tools = [
            {
                "name": "get_school_information",
                "description": (
                    "Get information about Wells Middle School from the school website. "
                    "Use this to answer questions about the school such as: staff, programs, "
                    "events, academics, clubs, sports, contact info, schedules, and announcements."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's question about the school"
                        },
                        "pages": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional list of specific page paths to scrape "
                                "(e.g., ['/about', '/staff']). Leave empty to use defaults."
                            )
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

        self.system_prompt = """You are a helpful assistant for Wells Middle School, part of the Dublin Unified School District in Dublin, California.

You help students, parents, and staff with questions about the school — including academics, staff, events, clubs, sports, schedules, and general information.

SCHOOL INFORMATION:
Website: https://wms.dublinusd.org/
District: Dublin Unified School District

CRITICAL RULES:
- NEVER guess, assume, or fabricate school information
- Always use the get_school_information tool to look up answers from the school website
- If you cannot find an answer from the website, say so clearly and suggest contacting the school directly
- Be friendly, concise, and helpful

When answering questions, use the get_school_information tool to retrieve up-to-date information from the school website."""

    def process_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        if tool_name == "get_school_information":
            pages = tool_input.get("pages", None)
            return scraper.get_school_info(pages)

        return "Tool not found"

    def clear_conversation(self, user_id: str = "default"):
        if user_id in self.conversations:
            del self.conversations[user_id]

    def chat(self, user_message: str, user_id: str = "default") -> str:
        """
        Process a user message and return a response.

        Args:
            user_message: The message from the user
            user_id: Unique identifier for the user (e.g., phone number)

        Returns:
            str: The agent's response
        """
        try:
            # Basic content filter
            inappropriate_words = ['fuck', 'shit', 'bitch', 'bastard']
            message_lower = user_message.lower()
            for word in inappropriate_words:
                if re.search(r'\b' + re.escape(word) + r'\b', message_lower):
                    return ("I'm sorry, but I can only respond to respectful inquiries. "
                            "Please keep communication kind and respectful. "
                            "How can I help you with a school-related question?")

            # Get or create conversation history
            if user_id not in self.conversations:
                self.conversations[user_id] = []

            self.conversations[user_id].append({
                "role": "user",
                "content": user_message
            })

            messages = self.conversations[user_id].copy()

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                tools=self.tools,
                messages=messages
            )

            # Agentic loop
            while response.stop_reason == "tool_use":
                tool_use_block = next(
                    (block for block in response.content if block.type == "tool_use"),
                    None
                )

                if not tool_use_block:
                    break

                tool_result = self.process_tool_call(tool_use_block.name, tool_use_block.input)

                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_block.id,
                            "content": tool_result
                        }
                    ]
                })

                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    tools=self.tools,
                    messages=messages
                )

            final_response = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_response += block.text

            if not final_response:
                final_response = "I'm not sure how to help with that. Please contact Wells Middle School directly."

            self.conversations[user_id].append({
                "role": "assistant",
                "content": final_response
            })

            # Keep last 20 messages to prevent memory overflow
            if len(self.conversations[user_id]) > 20:
                self.conversations[user_id] = self.conversations[user_id][-20:]

            return final_response

        except Exception as e:
            error_msg = f"Sorry, I encountered an error: {str(e)}"
            if user_id in self.conversations:
                self.conversations[user_id].append({
                    "role": "assistant",
                    "content": error_msg
                })
            return error_msg


# Singleton instance
agent = WellsMiddleSchoolAgent()
