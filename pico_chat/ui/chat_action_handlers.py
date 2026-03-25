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
            # Strip ANSI escape codes for clean clipboard content
            text_to_copy = strip_ansi(message.base_text)
            
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
        """Handle edit action for a focused message (user messages only)."""
        logger = logging.getLogger("tui")
        logger.info("Edit action triggered")
        
        # Store which message is being edited
        try:
            self.editing_message_index = self.chat_history_panel.messages.index(message)
        except ValueError:
            self.editing_message_index = None
        
        # Populate input field with message content
        self.input_component.update(message.base_text)
        
        # Switch focus to input
        self._last_focus_id = "input"
        self._update_focus_states()
        
        # Clear message focus
        self.chat_history_panel.clear_focus()
    
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
                self.message_queue.put_nowait((user_text, user_msg))
                logger.info(f"Retrying with message: {user_text[:50]}...")
            else:
                self.chat_history_panel.add_message(
                    "Could not find user message to retry",
                    msg_type=SysMsgError()
                )
        except ValueError:
            logger.error("Message not found in history")
    
    def handle_stop_action(self, message):
        """Handle stop action for ongoing generation."""
        logger = logging.getLogger("tui")
        logger.info("Stop action triggered")
        
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
            
            # Don't update the message - it will be replaced by ToolStart with DENIED status
            logger.info("Permission denied, waiting for tool result")
        else:
            logger.warning("Deny action called on non-permission message")
