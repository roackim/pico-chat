"""Action handlers for chat messages."""

import logging
import subprocess
from pico_chat.ui.tui.layout_utils import strip_ansi
from pico_chat.ui.tui.msg_types import UserMsg, SysMsg, SysMsgError


class ChatActionHandlers:
    """Mixin class providing action handlers for chat messages."""
    
    def handle_copy_action(self, message):
        """Handle copy action for a focused message."""
        logger = logging.getLogger("tui")
        
        try:
            # For tool call messages, build comprehensive debug output
            from pico_chat.ui.tui.msg_types import ToolCallMsg, AskPermissionMsg
            if isinstance(message.type, (ToolCallMsg, AskPermissionMsg)) and message.tool_name:
                import json
                
                # Build detailed tool call output
                lines = [
                    "=" * 60,
                    f"TOOL CALL: {message.tool_name}",
                    "=" * 60,
                    "",
                    "ARGUMENTS:",
                    "-" * 60,
                ]
                
                # Pretty-print arguments
                if message.tool_args:
                    try:
                        args_dict = json.loads(message.tool_args)
                        lines.append(json.dumps(args_dict, indent=2))
                    except:
                        lines.append(message.tool_args)
                else:
                    lines.append("(no arguments)")
                
                lines.extend(["", "STATUS:", "-" * 60])
                lines.append(message.tool_status or "pending")
                
                # Include output if available
                if message.tool_output:
                    lines.extend(["", "OUTPUT:", "-" * 60, message.tool_output])
                else:
                    lines.extend(["", "OUTPUT:", "-" * 60, "(no output yet)"])
                
                lines.append("")
                lines.append("=" * 60)
                
                text_to_copy = "\n".join(lines)
            else:
                # Strip ANSI escape codes for clean clipboard content
                text_to_copy = strip_ansi(message.base_text)
                # Ensure a trailing newline so pasting keeps the line break.
                if text_to_copy and not text_to_copy.endswith("\n"):
                    text_to_copy += "\n"
            
            # Try to copy to clipboard using various methods
            
            # Method 1: Try xclip (X11)
            try:
                subprocess.run(['xclip', '-selection', 'clipboard'], 
                             input=text_to_copy.encode(), 
                             check=True, 
                             stderr=subprocess.DEVNULL)
                logger.info("Message copied to clipboard (xclip)")
                self.chat_history_panel.add_message("Copied to clipboard", msg_type=SysMsg())
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # Method 2: Try xsel (X11 alternative)
            try:
                subprocess.run(['xsel', '--clipboard', '--input'], 
                             input=text_to_copy.encode(), 
                             check=True,
                             stderr=subprocess.DEVNULL)
                logger.info("Message copied to clipboard (xsel)")
                self.chat_history_panel.add_message("Copied to clipboard", msg_type=SysMsg())
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # Method 3: Try wl-copy (Wayland)
            try:
                subprocess.run(['wl-copy'], 
                             input=text_to_copy.encode(), 
                             check=True,
                             stderr=subprocess.DEVNULL)
                logger.info("Message copied to clipboard (wl-copy)")
                self.chat_history_panel.add_message("Copied to clipboard", msg_type=SysMsg())
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # If all methods fail
            logger.warning("No clipboard utility found (tried xclip, xsel, wl-copy)")
            self.chat_history_panel.add_message(
                "Could not copy: no clipboard utility found\nInstall xclip, xsel, or wl-copy",
                msg_type=SysMsgError()
            )
            
        except Exception as e:
            logger.error(f"Error copying to clipboard: {e}")
            self.chat_history_panel.add_message(f"Copy failed: {e}", msg_type=SysMsgError())
    
    def handle_edit_action(self, message):
        """Handle edit action — opens an in-place editor inside the message box.

        Raw (unrendered) text is shown with a cursor; Enter confirms, Esc cancels.
        - Paused AI message → edit captured thinking prefill
        - Finalized ThinkingMsg → edit reasoning as thinking prefill for regeneration
        - Finalized PicoMsg (content) → find preceding ThinkingMsg and edit that
        - UserMsg → edit message text; wipes subsequent messages on confirm
        """
        logger = logging.getLogger("tui")
        logger.info("Edit action triggered (inline)")

        from pico_chat.ui.tui.msg_types import PicoMsg as _PicoMsg, ThinkingMsg as _ThinkingMsg, UserMsg as _UserMsg, SysMsgError as _SysMsgError

        # --- Paused AI message: edit the captured thinking prefill ---
        if getattr(message, 'is_paused', False):
            prefill = getattr(self.agent, '_pending_thinking_prefill', None) or ""
            paused_input = getattr(self, '_paused_user_input', None)
            paused_msg_ref = getattr(self, '_paused_user_msg', None)

            def _submit_paused(text):
                self.agent.set_thinking_prefill(text)
                self._paused_user_input = paused_input
                self._paused_user_msg   = paused_msg_ref
                self.handle_resume_action(None)

            self.chat_history_panel.start_inline_edit(message, prefill, _submit_paused)
            self._last_focus_id = "history"
            self._update_focus_states()
            return

        # --- Finalized AI message (ThinkingMsg / PicoMsg): edit as thinking prefill ---
        if isinstance(message.type, _PicoMsg):
            self.stop_generation()
            try:
                msg_index = self.chat_history_panel.messages.index(message)
            except ValueError:
                return
            user_msg = None
            preceding_thinking_msg = None
            for i in range(msg_index - 1, -1, -1):
                m = self.chat_history_panel.messages[i]
                if isinstance(m.type, _UserMsg):
                    user_msg = m
                    break
                if preceding_thinking_msg is None and isinstance(m.type, _ThinkingMsg):
                    preceding_thinking_msg = m
            if user_msg is None:
                self.chat_history_panel.add_message(
                    "Can't edit: no preceding user message found.",
                    msg_type=_SysMsgError()
                )
                return
            if isinstance(message.type, _ThinkingMsg):
                prefill_text = message.base_text
            elif preceding_thinking_msg is not None:
                prefill_text = preceding_thinking_msg.base_text
            else:
                prefill_text = ""

            _paused_input = user_msg.base_text
            _paused_msg   = user_msg

            def _submit_ai(text):
                self.agent.set_thinking_prefill(text)
                self._paused_user_input = _paused_input
                self._paused_user_msg   = _paused_msg
                self.handle_resume_action(None)

            self.chat_history_panel.start_inline_edit(message, prefill_text, _submit_ai)
            self._last_focus_id = "history"
            self._update_focus_states()
            return

        # --- Normal user message: edit text in-place, wipe subsequent messages ---
        self.stop_generation()

        def _submit_user(text):
            try:
                idx = self.chat_history_panel.messages.index(message)
            except ValueError:
                return
            # Delete harness messages from this message forward (inclusive)
            if message.harness_message_ids:
                harness_id = message.harness_message_ids[0]
                self.agent.delete_messages_after_id(harness_id, inclusive=True)
            message.harness_message_ids = []
            # Update the message text in-place
            message.set_text(text)
            # Remove all subsequent UI messages
            messages_to_remove = len(self.chat_history_panel.messages) - idx - 1
            for _ in range(messages_to_remove):
                self.chat_history_panel.remove_last_message()
            # Re-queue
            self.chat_history_panel.auto_scroll = True
            self._enqueue_message(text, message)

        self.chat_history_panel.start_inline_edit(
            message,
            message.command_text if message.command_text else message.base_text,
            _submit_user
        )
        self._last_focus_id = "history"
        self._update_focus_states()


    def handle_delete_action(self, message):
        """Delete a message and all messages after it from both UI and harness."""
        logger = logging.getLogger("tui")
        logger.info("Delete action triggered")

        self.stop_generation()

        try:
            idx = self.chat_history_panel.messages.index(message)
        except ValueError:
            return

        # Remove from harness (inclusive: removes this message and everything after)
        if message.harness_message_ids:
            harness_id = message.harness_message_ids[0]
            self.agent.delete_messages_after_id(harness_id, inclusive=True)

        # Remove from UI: this message and all after it
        to_remove = len(self.chat_history_panel.messages) - idx
        for _ in range(to_remove):
            self.chat_history_panel.remove_last_message()


    def handle_retry_action(self, message):
        """Handle retry action for a message (regenerate response)."""
        logger = logging.getLogger("tui")
        logger.info("Retry action triggered")
        
        # Stop any ongoing generation first
        if self.stop_generation():
            logger.info("Stopped ongoing generation for retry")
        
        # Find the previous user message to retry using harness IDs
        try:
            msg_index = self.chat_history_panel.messages.index(message)
            
            # Look backwards for the last user message
            user_msg = None
            user_msg_index = None
            for i in range(msg_index - 1, -1, -1):
                msg = self.chat_history_panel.messages[i]
                if isinstance(msg.type, UserMsg):
                    user_msg = msg
                    user_msg_index = i
                    break
            
            if user_msg and user_msg.harness_message_ids:
                # Use the harness ID to delete from harness history
                user_harness_id = user_msg.harness_message_ids[0]
                
                # Delete user message AND everything after from harness (will be re-added on resubmit)
                if self.agent.delete_messages_after_id(user_harness_id, inclusive=True):
                    logger.info(f"Deleted harness messages after ID {user_harness_id} (inclusive)")
                
                # Remove UI messages AFTER the user message (keep user visible)
                messages_to_remove = len(self.chat_history_panel.messages) - user_msg_index - 1
                for _ in range(messages_to_remove):
                    self.chat_history_panel.remove_last_message()
                
                # Clear the user message's harness ID (will get new one)
                user_msg.harness_message_ids = []
                
                # Resubmit the user message (as tuple to match normal submit)
                user_text = user_msg.base_text
                self.chat_history_panel.auto_scroll = True
                self._enqueue_message(user_text, user_msg)
                logger.info(f"Retrying with message: {user_text[:50]}...")
            else:
                self.chat_history_panel.add_message(
                    "Could not find user message to retry",
                    msg_type=SysMsgError()
                )
        except ValueError:
            logger.error("Message not found in history")
    
    def handle_stop_action(self, message):
        """Handle stop action for ongoing generation, or a running command."""
        logger = logging.getLogger("tui")
        logger.info("Stop action triggered")

        from pico_chat.ui.tui.msg_types import ToolCallMsg, ToolDraftMsg
        # For a running tool message, stop just that command (not the whole
        # generation) so the model can continue with other work.
        if isinstance(message.type, (ToolCallMsg, ToolDraftMsg)) and not message.finalized:
            stopped = self.agent.stop_tool() if hasattr(self.agent, "stop_tool") else False
            if stopped:
                message.tool_status = "cancelled"
                message.tool_output = "[stopped by user]"
                message.finalize()
                message.rebuild_tool_display()
                logger.info("Running command stopped by user")
                return
            logger.info("No running command to stop")

        if self.stop_generation():
            logger.info("Generation stopped by user")
            # The cancellation will be handled in _process_generation
        else:
            logger.info("No active generation to stop")
    
    def handle_allow_action(self, message):
        """Handle allow action for tool permission requests."""
        logger = logging.getLogger("tui")
        logger.info("Allow action triggered")
        
        from pico_chat.ui.tui.msg_types import AskPermissionMsg
        from pico_chat.ui.tui.colors import theme
        
        # Check if this is a permission request message
        if isinstance(message.type, AskPermissionMsg):
            # Send approval to harness
            logger.info("Sending approve to harness")
            self.agent.set_user_response("approve")
            self.pending_permission_prompt = None
            
            # Focus input field
            self._last_focus_id = "input"
            self._update_focus_states()
            
            # Don't update the message - it will be replaced by ToolStart
            logger.info("Permission granted, waiting for tool execution")
        else:
            logger.warning("Allow action called on non-permission message")
    
    def handle_deny_action(self, message):
        """Handle deny action for tool permission requests."""
        logger = logging.getLogger("tui")
        logger.info("Deny action triggered")
        
        from pico_chat.ui.tui.msg_types import AskPermissionMsg
        from pico_chat.ui.tui.colors import theme
        
        # Check if this is a permission request message
        if isinstance(message.type, AskPermissionMsg):
            # Send denial to harness
            logger.info("Sending deny to harness")
            self.agent.set_user_response("deny")
            self.pending_permission_prompt = None
            
            # Focus input field
            self._last_focus_id = "input"
            self._update_focus_states()
            
            # Don't update the message - it will be replaced by ToolStart with DENIED status
            logger.info("Permission denied, waiting for tool result")
        else:
            logger.warning("Deny action called on non-permission message")
    
    def handle_output_action(self, message):
        """Handle output action for tool messages - toggle output visibility."""
        logger = logging.getLogger("tui")
        logger.info("Output toggle action triggered")
        
        from pico_chat.ui.tui.msg_types import ToolCallMsg, AskPermissionMsg
        
        # Check if this is a tool message
        if isinstance(message.type, (ToolCallMsg, AskPermissionMsg)):
            # Toggle output visibility
            message.show_output = not message.show_output
            message.rebuild_tool_display()
            logger.info(f"Tool output {'shown' if message.show_output else 'hidden'}")
        else:
            logger.warning("Output action called on non-tool message")

    # ------------------------------------------------------------------
    # Steer / Pause / Resume
    # ------------------------------------------------------------------

    def handle_steer_action(self, message):
        """Inject the queued user message as a thinking prefill for the current
        (or next) generation, then cancel-and-restart that generation.

        The steer message is consumed: it's visually replaced by a SysMsg and
        the original user input is re-queued so the LLM answers it with the
        enriched thinking prefix.
        """
        logger = logging.getLogger("tui")
        logger.info("Steer action triggered")

        from pico_chat.ui.tui.msg_types import UserMsg

        if not isinstance(message.type, UserMsg) or not message.is_queued:
            logger.warning("Steer action called on non-queued UserMsg")
            return

        steer_content = strip_ansi(message.base_text).strip()
        if not steer_content:
            return

        # Build the prefill: existing thinking so far + the steer text
        current_reasoning = self.agent.get_current_reasoning()
        if current_reasoning:
            prefill = current_reasoning + "\n" + steer_content
        else:
            prefill = steer_content

        self.agent.set_thinking_prefill(prefill)
        logger.info(f"Thinking prefill set ({len(prefill)} chars)")

        # Mark message as consumed (no longer queued as a user message)
        message.is_queued = False
        message.is_steered = True   # prevent agent_worker from processing it normally
        message.box.mark_changed()

        # Signal agent_worker to re-queue the active user input after cancellation
        self._requeue_after_cancel = True

        # Cancel current generation so it restarts with the prefill
        self.stop_generation()

        # Switch focus back to input
        self._last_focus_id = "input"
        self._update_focus_states()

    def handle_pause_action(self, message):
        """Cancel the current generation and capture the thinking accumulated so
        far as a prefill.  The message is marked as paused so the user can
        resume later.
        """
        logger = logging.getLogger("tui")
        logger.info("Pause action triggered")

        if not self.stop_generation():
            logger.info("No active generation to pause")
            self.chat_history_panel.add_message("No active generation to pause.", msg_type=SysMsg())
            return

        # Capture reasoning so far as the resume prefill
        current_reasoning = self.agent.get_current_reasoning()
        if current_reasoning:
            self.agent.set_thinking_prefill(current_reasoning)

        # Mark the message as paused if a real message object was supplied
        if message is not None:
            message.is_paused = True
            message.set_title("paused")
            message.box.mark_changed()

        # Store pause context so /resume and handle_resume_action can restart
        self._paused_user_input = getattr(self, "_active_user_input", None)
        self._paused_user_msg   = getattr(self, "_active_user_msg", None)
        logger.info("Generation paused; thinking prefill captured for resume")

        self._last_focus_id = "input"
        self._update_focus_states()

    def handle_resume_action(self, message):
        """Re-queue the original user message so it is regenerated from where
        thinking was paused.
        """
        logger = logging.getLogger("tui")
        logger.info("Resume action triggered")

        paused_input = getattr(self, "_paused_user_input", None)
        paused_msg   = getattr(self, "_paused_user_msg", None)

        if not paused_input or not paused_msg:
            self.chat_history_panel.add_message(
                "Nothing to resume.", msg_type=SysMsg()
            )
            return

        # Remove the user message and everything after from harness so it can be
        # re-added cleanly (with thinking prefill injected at call time).
        if paused_msg.harness_message_ids:
            harness_id = paused_msg.harness_message_ids[0]
            self.agent.delete_messages_after_id(harness_id, inclusive=True)
        paused_msg.harness_message_ids = []

        # Remove all UI messages after the original user message
        try:
            idx = self.chat_history_panel.messages.index(paused_msg)
            to_remove = len(self.chat_history_panel.messages) - idx - 1
            for _ in range(to_remove):
                self.chat_history_panel.remove_last_message()
        except ValueError:
            pass

        # Restore visual state of user message (no longer paused)
        paused_msg.is_paused = False

        # Re-queue the original user input (thinking prefill already set)
        self.chat_history_panel.auto_scroll = True
        self._enqueue_message(paused_input, paused_msg)

        # Clear pause state
        self._paused_user_input = None
        self._paused_user_msg   = None

        self._last_focus_id = "input"
        self._update_focus_states()

    def handle_prefill_command(self, user_text: str):
        """Submit a user message without starting generation.

        Adds the user message to harness history and shows an empty paused
        response so the user can press [e] to type the thinking prefill,
        then [u] (or /resume) to start generation from that point.
        """
        logger = logging.getLogger("tui")
        logger.info(f"Prefill command: {user_text[:60]}")

        # Stop any active generation first
        self.stop_generation()

        from pico_chat.ui.tui.msg_types import UserMsg, PicoMsg

        # Add user message directly to harness history (no generation)
        harness_id = self.agent._add_message_to_history("user", user_text)

        # Create UI user message linked to the harness entry
        user_msg = self.chat_history_panel.add_message(user_text, msg_type=UserMsg())
        user_msg.harness_message_ids = [harness_id]
        user_msg.finalize()

        # Create an empty paused response message the user will edit
        paused_response = self.chat_history_panel.add_message("", msg_type=PicoMsg())
        paused_response.is_paused = True
        paused_response.set_title("paused — press [e] to edit thinking prefill")
        paused_response.finalize()

        # Store pause context so [u] / /resume works
        self._paused_user_input = user_text
        self._paused_user_msg   = user_msg

        self.chat_history_panel.auto_scroll = True
        # Move focus to the paused response so [e] is immediately available
        last_idx = len(self.chat_history_panel.messages) - 1
        self.chat_history_panel.set_focused_message(last_idx)
        # Switch keyboard focus to the chat panel
        self._last_focus_id = "chat"
        self._update_focus_states()
