import logging

from director.agents.base import BaseAgent, AgentResponse, AgentStatus
from director.core.session import (
    Session,
    VideoContent,
    VideoData,
    MsgStatus,
    ContextMessage,
    RoleTypes,
)
from director.llm import get_default_llm
from director.llm.base import LLMResponse
from director.agents.editing.code_executor import CodeExecutor
from director.agents.editing.media_handler import MediaHandler

logger = logging.getLogger(__name__)


EDITING_AGENT_PARAMETERS = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": (
                "Detailed editing prompt for the editing agent to edit the "
                "videos. Always include media IDs in the prompt."
            ),
        },
        "collection_id": {
            "type": "string",
            "description": "The ID of the collection to process.",
        },
    },
    "required": ["prompt", "collection_id"],
}

EDITING_PROMPT = """
You are a video editing agent using the VideoDB Editor API.

When needed, call get_media to verify media IDs and durations.
When ready, call code_executor with complete Python code that:
- Uses videodb.editor classes (Timeline, Track, Clip, VideoAsset, AudioAsset,
  ImageAsset, TextAsset, CaptionAsset, filters, transitions as needed)
- Assigns the final stream URL to a variable named stream_url

Keep code self-contained and executable.
""".strip()


class EditingAgent(BaseAgent):
    """Agent for editing videos and audio files using VideoDB editor timeline."""

    def __init__(self, session: Session, **kwargs):
        self.agent_name = "editing"
        self.description = (
            "Timeline-based video editor for cutting, combining, and "
            "transforming media."
        )
        self.parameters = EDITING_AGENT_PARAMETERS
        super().__init__(session=session, **kwargs)

        self.llm = get_default_llm()
        self.agent_context: list[ContextMessage] = list(
            self.session.get_context_messages()
        )

        self.code_executor = CodeExecutor(session)
        self.media_handler = None
        self.editing_response = None
        self.iterations = 0
        self.stop_flag = False

        self.tools = self._define_tools()
        logger.info("EditingAgent initialized with VideoDB LLM interface")

    def _update_context(self, context: ContextMessage):
        self.agent_context.append(context)
        self.session.reasoning_context = self.agent_context

    def _define_tools(self):
        return [
            {
                "name": "get_media",
                "description": "Fetch media details from VideoDB",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "media_id": {
                            "type": "string",
                            "description": "ID of the media to fetch",
                        },
                        "media_type": {
                            "type": "string",
                            "description": "Type of media",
                            "enum": ["audio", "video", "image"],
                        },
                        "step_reasoning": {
                            "type": "string",
                            "description": (
                                "Short description of the step being run"
                            ),
                        },
                    },
                    "required": ["media_id", "media_type", "step_reasoning"],
                },
            },
            {
                "name": "code_executor",
                "description": "Execute Timeline Python code",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Executable Timeline Python code",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of the code",
                        },
                        "step_reasoning": {
                            "type": "string",
                            "description": (
                                "Short summary of the editing operation"
                            ),
                        },
                    },
                    "required": ["code", "description", "step_reasoning"],
                },
            },
        ]

    def get_media(
        self,
        media_id: str,
        media_type: str,
        step_reasoning: str = None,
    ) -> AgentResponse:
        if step_reasoning:
            self.output_message.actions.append(step_reasoning)
            self.output_message.push_update()
        return self.media_handler.get_media(media_id, media_type)

    def execute_code(
        self,
        code: str,
        description: str,
        step_reasoning: str = None,
    ) -> AgentResponse:
        if step_reasoning:
            self.output_message.actions.append(step_reasoning)
            self.output_message.push_update()
        return self.code_executor.execute_code(code, description)

    def run_llm(self):
        llm_response: LLMResponse = self.llm.chat_completions(
            messages=[message.to_llm_msg() for message in self.agent_context],
            tools=self.tools,
        )

        if llm_response.tool_calls:
            self._update_context(
                ContextMessage(
                    content=llm_response.content,
                    tool_calls=llm_response.tool_calls,
                    role=RoleTypes.assistant,
                )
            )
            for tool_call in llm_response.tool_calls:
                tool_name = tool_call["tool"]["name"]
                tool_args = tool_call["tool"]["arguments"]

                if tool_name == "code_executor":
                    response = self.execute_code(**tool_args)
                    self.editing_response = response
                elif tool_name == "get_media":
                    response = self.get_media(**tool_args)
                else:
                    response = AgentResponse(
                        data={},
                        message=f"Unknown tool: {tool_name}",
                        status=AgentStatus.ERROR,
                    )

                self._update_context(
                    ContextMessage(
                        content=response.__str__(),
                        tool_call_id=tool_call["id"],
                        role=RoleTypes.tool,
                    )
                )

        if (
            llm_response.finish_reason in {"stop", "end_turn"}
            or self.iterations == 0
        ):
            if self.editing_response or self.iterations == 0:
                self._update_context(
                    ContextMessage(
                        content=llm_response.content,
                        role=RoleTypes.assistant,
                    )
                )
                self.stop_flag = True
            else:
                self._update_context(
                    ContextMessage(
                        content=llm_response.content,
                        role=RoleTypes.assistant,
                    )
                )
                self.editing_response = AgentResponse(
                    data={},
                    message=llm_response.content,
                    status=AgentStatus.ERROR,
                )

    def run(self, prompt: str, collection_id: str, *args, **kwargs) -> AgentResponse:
        try:
            self.prompt = prompt
            self.collection_id = collection_id
            self.iterations = 25
            self.stop_flag = False
            self.editing_response = None

            self.media_handler = MediaHandler(collection_id)
            self.output_message.actions.append(
                "Preparing your editing workspace..."
            )

            video_content = VideoContent(
                agent_name=self.agent_name,
                status=MsgStatus.progress,
                status_message="Generating editing instructions...",
            )
            self.output_message.content.append(video_content)
            self.output_message.push_update()

            input_context = ContextMessage(
                content=f"{self.prompt}", role=RoleTypes.user
            )
            if not any(
                message.role == RoleTypes.system
                and message.content == EDITING_PROMPT
                for message in self.agent_context
            ):
                system_context = ContextMessage(
                    content=EDITING_PROMPT, role=RoleTypes.system
                )
                self._update_context(system_context)
            self._update_context(input_context)

            self.output_message.actions.append("Crafting your video edit...")
            self.output_message.push_update()

            iteration = 0
            while self.iterations > 0:
                self.iterations -= 1
                logger.info(f"Code generation iteration {iteration}")

                if self.stop_flag:
                    break

                self.run_llm()
                iteration += 1
            logger.info("Timeline code generation completed")

            if (
                self.editing_response
                and self.editing_response.status == AgentStatus.SUCCESS
            ):
                stream_url = self.editing_response.data.get("stream_url")

                if stream_url:
                    video_content.video = VideoData(stream_url=stream_url)
                    video_content.status = MsgStatus.success
                    video_content.status_message = (
                        "Editing instructions executed successfully."
                    )
                    self.output_message.actions.append("Video edit complete!")
                else:
                    video_content.status = MsgStatus.error
                    video_content.status_message = (
                        "No stream URL generated from Timeline execution."
                    )
            else:
                video_content.status = MsgStatus.error
                video_content.status_message = (
                    "Something went wrong with Timeline execution. Please try again."
                )

            self.output_message.publish()

        except Exception as e:
            logger.exception(f"Error in {self.agent_name}")
            video_content.status = MsgStatus.error
            video_content.status_message = "Error in Timeline code generation."
            self.output_message.publish()
            return AgentResponse(
                status=AgentStatus.ERROR, message=f"Agent failed with error: {e}"
            )

        final_status = AgentStatus.SUCCESS
        final_message = "Timeline code generation completed successfully."
        final_data = {
            "collection_id": collection_id,
            "editing_response": self.editing_response.data
            if self.editing_response
            else {},
        }

        if not self.editing_response:
            final_status = AgentStatus.ERROR
            final_message = "No editing response produced by code generator."
        else:
            inner_success = self.editing_response.data.get("execution_success")
            if (
                self.editing_response.status != AgentStatus.SUCCESS
                or inner_success is False
            ):
                final_status = AgentStatus.ERROR
                message = self.editing_response.message
                err = self.editing_response.data.get("error")
                err_type = self.editing_response.data.get("error_type")
                final_message = (
                    "Timeline execution failed "
                    f"{message}, error: "
                    f"{err_type + ': ' if err_type else ''}{err}"
                )

        return AgentResponse(
            status=final_status,
            message=final_message,
            data=final_data,
        )
