"""Maps harness generation events onto transcript messages.

``process_generation`` drives one ``agent.chat()`` stream and translates each
harness event into UI mutations on the app. It lives outside ``app.py`` so the
event→UI mapping can be read on its own.
"""
from __future__ import annotations

import asyncio
import logging

from pico_chat.harness import events
from pico_chat.ui.chat_message import Message
from pico_chat.ui.tui.msg_types import (
    AskPermissionMsg,
    MsgType,
    PicoMsg,
    SysMsg,
    SysMsgError,
    ThinkingMsg,
    ToolCallMsg,
    ToolDraftMsg,
)


logger = logging.getLogger("tui")


async def process_generation(app, user_input, user_msg) -> None:
    """Process a single generation request, mapping events to messages."""
    logger.info(f"Starting generation for user input: {user_input[:50]}...")

    chat = app.chat_history_panel
    agent = app.agent
    app.refresh_status_bar()
    # No placeholder status message: the first real chunk creates its own
    # message. This keeps the conversation free of transient "Sending
    # request..." / "Processing results..." clutter.
    current_msg = None
    current_msg_type = None
    current_harness_ids = []

    def ensure_tool_message_type(msg: Message, target_type: MsgType) -> Message:
        if isinstance(msg.type, type(target_type)):
            return msg
        new_msg = chat.new_message(
            "",
            msg_type=target_type,
            harness_message_ids=msg.harness_message_ids or current_harness_ids,
        )
        new_msg.tool_name = msg.tool_name
        new_msg.tool_args = msg.tool_args
        new_msg.tool_output = msg.tool_output
        new_msg.tool_status = msg.tool_status
        new_msg.show_output = msg.show_output
        chat.replace_message(msg, new_msg)
        return new_msg

    if app.compositor and hasattr(app.compositor, "set_streaming_active"):
        app.compositor.set_streaming_active(True)

    # Process streaming events from Harness
    try:
        async for event in agent.chat(user_input):
            if app.compositor and hasattr(app.compositor, "request_render"):
                app.compositor.request_render()

            if isinstance(event, events.Start):
                current_harness_ids = [event.message_id]
                logger.debug(f"Start: {event.role} with ID {event.message_id}")

                if event.role == "user":
                    # Link the user message that was passed through the queue
                    if not user_msg.harness_message_ids:
                        user_msg.harness_message_ids = [event.message_id]
                        logger.debug(f"Linked user message to harness ID {event.message_id}")

            elif isinstance(event, events.Reasoning):
                # If not currently in a thinking message, create one
                if current_msg_type != ThinkingMsg:
                    if current_msg is not None:
                        # Finalize previous and create new
                        current_msg.finalize()
                    current_msg = chat.add_message("", msg_type=ThinkingMsg(), harness_message_ids=current_harness_ids)
                    # Thinking folds to a single line by default; expand on focus.
                    current_msg.set_collapsed(True)
                    current_msg_type = ThinkingMsg

                current_msg.append(event.text)

            elif isinstance(event, events.Token):
                # If not currently in a content message, create one
                if current_msg_type != PicoMsg:
                    if current_msg is not None:
                        # Finalize previous and create new
                        current_msg.finalize()
                    current_msg = chat.add_message("", msg_type=PicoMsg(), harness_message_ids=current_harness_ids)
                    current_msg_type = PicoMsg

                current_msg.append(event.text)

            elif isinstance(event, events.ToolCall):
                tool_id = event.id
                msg = app.active_tool_messages.get(tool_id)
                preserve_active_text_stream = current_msg_type in (ThinkingMsg, PicoMsg)

                # Flush any incomplete text message before showing tool draft
                if current_msg_type in (ThinkingMsg, PicoMsg) and current_msg:
                    current_msg.finalize()

                if not msg:
                    msg = chat.add_message("", msg_type=ToolDraftMsg(), harness_message_ids=current_harness_ids)
                    app.active_tool_messages[tool_id] = msg

                msg = ensure_tool_message_type(msg, ToolDraftMsg())
                app.active_tool_messages[tool_id] = msg
                msg.tool_name = event.name or msg.tool_name
                msg.tool_args = event.args
                msg.tool_status = "drafting"
                msg.rebuild_tool_display()

                if not preserve_active_text_stream:
                    current_msg = msg
                    current_msg_type = type(msg.type)

            elif isinstance(event, events.PermissionRequest):
                tool_id = event.id

                # Flush any incomplete text message before showing tool request
                if current_msg_type in (ThinkingMsg, PicoMsg) and current_msg:
                    current_msg.finalize()

                msg = app.active_tool_messages.get(tool_id)

                if event.auto:
                    # Auto-decision: show status marker
                    if not msg:
                        msg = chat.add_message(
                            "",  # Will be built by rebuild_tool_display
                            msg_type=ToolCallMsg(),
                            harness_message_ids=current_harness_ids,
                        )
                        app.active_tool_messages[tool_id] = msg

                    msg = ensure_tool_message_type(msg, ToolCallMsg())
                    app.active_tool_messages[tool_id] = msg
                    msg.tool_name = event.name
                    msg.tool_args = event.args
                    msg.tool_status = "auto-approved"
                    msg.rebuild_tool_display()
                    app.pending_permission_prompt = None
                else:
                    # Need user permission - show request
                    if not msg:
                        msg = chat.add_message(
                            "",
                            msg_type=AskPermissionMsg(),
                            harness_message_ids=current_harness_ids,
                        )
                        app.active_tool_messages[tool_id] = msg

                    msg = ensure_tool_message_type(msg, AskPermissionMsg())
                    app.active_tool_messages[tool_id] = msg
                    msg.tool_name = event.name
                    msg.tool_args = event.args
                    msg.tool_status = None
                    msg.rebuild_tool_display()

                    # Auto-focus for user action
                    try:
                        msg_index = chat.messages.index(msg)
                        chat.set_focused_message(msg_index)
                    except ValueError:
                        pass
                    app._set_app_focus("history")

                    # Force compositor render to show actions immediately
                    if app.compositor:
                        app.compositor.render()

                    # Store prompt for handler
                    app.pending_permission_prompt = event.prompt

                current_msg = msg
                current_msg_type = type(msg.type)

            elif isinstance(event, events.ToolResult):
                tool_id = event.id
                msg = app.active_tool_messages.get(tool_id)
                if msg:
                    msg = ensure_tool_message_type(msg, ToolCallMsg())
                    app.active_tool_messages[tool_id] = msg
                    msg.tool_name = event.name
                    if event.outcome == "completed":
                        msg.tool_status = "completed"
                        msg.tool_output = event.output
                    elif event.outcome == "denied":
                        msg.tool_status = "denied"
                        msg.tool_output = event.output
                        msg.show_output = True  # Always show denial reason
                    else:
                        msg.tool_status = "error"
                        msg.tool_output = event.output
                        msg.show_output = True  # Always show errors
                    msg.rebuild_tool_display()
                    msg.finalize()
                    del app.active_tool_messages[tool_id]
                app.pending_permission_prompt = None

            elif isinstance(event, events.Usage):
                # Update message metrics (for live display in footer).
                # Only update for thinking/content messages, not tool messages.
                if current_msg_type in (ThinkingMsg, PicoMsg):
                    current_msg.update_metrics(
                        tokens=event.tokens,
                        tokens_per_second=event.tokens_per_second,
                        ttft_ms=event.ttft_ms,
                        duration_ms=event.duration_ms,
                    )
                app.refresh_status_bar()

            elif isinstance(event, events.Error):
                if current_msg is not None:
                    current_msg.finalize()
                    current_msg = None
                    current_msg_type = None
                chat.add_message(event.message, msg_type=SysMsgError())

            elif isinstance(event, events.Done):
                pass

            # Ensure we scroll to bottom if needed
            if chat.auto_scroll:
                chat.scroll_offset = 0
                # Auto-focus input when new messages arrive (if at bottom)
                # BUT: Don't steal focus if user has explicitly focused a message
                if app._last_focus_id != "input" and chat.focused_message_index is None:
                    app._set_app_focus("input")

            # Yield to let the compositor render the update
            await asyncio.sleep(0)

    except asyncio.CancelledError:
        # Finalize current message and add a plain SysMsg notification.
        # Avoid appending ANSI codes to a MarkdownComponent message (PicoMsg)
        # since the component would render the escape sequences as literal text.
        if current_msg is not None:
            current_msg.finalize()
        chat.add_message("[Generation stopped]", msg_type=SysMsg())
        raise

    except Exception as e:
        raise e

    finally:
        if app.compositor and hasattr(app.compositor, "set_streaming_active"):
            app.compositor.set_streaming_active(False)
        if current_msg is not None:
            current_msg.finalized = True
            current_msg.update_actions()
