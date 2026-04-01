"""Chat message representation with formatting and action support."""

from typing import Optional
from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme, RGB
from pico_chat.ui.tui.components import TextComponent, Box
from pico_chat.ui.tui.layout_utils import wrap_text
from pico_chat.ui.tui.msg_types import MsgType, MsgAction
from pico_chat.ui.tui import msg_types


class Message:
    """Represents a message in the chat history with formatting support."""
    
    def __init__(self,
                 text: str,
                 msg_type: MsgType = None,
                 max_width: int = 80,
                 left_pad: int = pico_cfg.config.ui_msg_h_padding,
                 right_pad: int = pico_cfg.config.ui_msg_h_padding,
                 title: str = None,
                 frame_color: RGB = None,
                 content_color: RGB = None,
                 left_margin: int = 0,
                 right_margin: int = 0,
                 harness_message_ids: list = None,
):
        """Initialize a message.
        
        Args:
            text: The raw message text
            msg_type: The type of message (determines default formatting)
            max_width: Maximum width for line wrapping
            left_pad: Number of spaces to pad the left side
            right_pad: Number of spaces to pad the right side
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            content_color: Optional override for the content text color
            left_margin: Number of spaces to pad the left side of the box
            right_margin: Number of spaces to pad the right side of the box
            harness_message_ids: List of harness message IDs this UI message references
        """
        
        self.type = msg_type or MsgType()
        
        # Track which harness messages this UI message represents
        self.harness_message_ids = harness_message_ids or []
        
        # Resolve defaults from msg_type if not provided
        if title is None:
            title = self.type.title
        
        if frame_color is None:
            color_name = self.type.frame_color
            frame_color = getattr(theme, color_name, theme.DEFAULT)
            
        if content_color is None and self.type.content_color:
            color_name = self.type.content_color
            content_color = getattr(theme, color_name, None)
        
        self.base_text = text
        self.max_width = max_width
        self.left_pad = left_pad
        self.right_pad = right_pad
        self.title = title
        self.frame_color = frame_color
        self.left_margin = left_margin
        self.right_margin = right_margin
        self.formatted_text = self._format_line_wrap()
        self.component = TextComponent(self.formatted_text, fg=content_color)
        self.finalized = False  # Whether this message is finalized
        
        # Tool-specific metadata
        self.tool_name: Optional[str] = None
        self.tool_args: Optional[str] = None
        self.tool_output: Optional[str] = None
        self.tool_status: Optional[str] = None  # "approved", "denied", "completed", etc.
        self.show_output: bool = False  # Toggle for output visibility
        
        # Generation metrics
        self.metrics_tokens: int = 0
        self.metrics_tokens_per_second: float = 0.0
        self.metrics_ttft_ms: Optional[float] = None
        self.metrics_duration_ms: Optional[float] = None
        
        self.box = Box(
            self.component,
            parent_msg=self
        )
    
    def finalize(self):
        self.finalized = True
        self.box.mark_changed()  # Finalization affects actions display
    
    def get_active_actions(self):
        """Get the list of active actions based on message state.
        
        Returns actions excluding STOP if message is finalized.
        """
        actions = list(self.type.actions)
        
        # Remove STOP action if message is finalized
        
        if isinstance(self.type, msg_types.PicoMsg): # Pico logic
            if self.finalized:
                actions = [a for a in actions if a != MsgAction.STOP]
        
            if not self.finalized:
                actions = [a for a in actions if a != MsgAction.DELETE]
        
        
        
        return actions
    
    def update_actions(self):
        """Update the box's actions list based on current state.
        
        Note: This is now a no-op since Box pulls actions dynamically from parent_msg.
        Kept for backward compatibility.
        """
        pass
    
    def set_title(self, title: str):
        """Update the title of the message box."""
        self.title = title
        self.box.title = title
        self.box.mark_changed()  # Title changed

    def set_frame_color(self, color: RGB):
        """Update the frame color of the message box."""
        self.frame_color = color
        self.box.fg = color
        self.box.mark_changed()  # Color changed

    def set_content_color(self, color: RGB):
        """Update the content color of the message."""
        self.component.fg = color
        self.box.mark_changed()  # Color changed
    
    def set_focused(self, focused: bool):
        """Set the focused state of this message."""
        self.box.set_focused(focused)
    
    def _format_line_wrap(self) -> str:
        """Format the message text with smart word wrapping and padding.
        
        Uses the provided left and right padding for each line.
        """
        if self.max_width is None or self.max_width <= 0:
            return self.base_text
        
        # Calculate available width for content after padding
        content_width = self.max_width - self.left_pad - self.right_pad
        if content_width < 1:
            content_width = 1
        
        # Wrap text into lines based on content_width
        # We wrap each line of base_text separately to preserve existing newlines
        lines = []
        base_text = self.base_text.rstrip('\n')
        for line in base_text.split('\n'):
            if not line:
                # Add an empty line if there's a newline in the middle of text
                lines.append("")
                continue
                
            # Wrap the line
            wrapped = wrap_text(line, content_width, padding_width=0, first_line_padding=False)
            for w_line in wrapped.split('\n'):
                # Apply left padding
                lines.append(" " * self.left_pad + w_line)
        
        return "\n".join(lines)
    
    def reformat(self, max_width: int) -> str:
        """Reformat the message with a new maximum width.
        
        Args:
            max_width: New maximum width for line wrapping
            
        Returns:
            The newly formatted text
        """
        self.max_width = max_width
        self.formatted_text = self._format_line_wrap()
        self.component.update(self.formatted_text)
        self.box.mark_changed()  # Content changed, need to re-render
        return self.formatted_text
    
    def get_formatted(self) -> str:
        """Get the current formatted text."""
        return self.formatted_text

    def get_component(self):
        """Get the TUI component for this message."""
        return self.box

    def set_text(self, new_text: str):
        """Set new text for the message and reformat."""
        self.base_text = new_text
        self.reformat(self.max_width)

    def append(self, text: str):
        """Append text to the message and reformat."""
        # If message is currently empty or whitespace-only, strip leading whitespace from first append
        if not self.base_text.strip():
            text = text.lstrip()
        self.base_text += text
        self.reformat(self.max_width)
    
    def rebuild_tool_display(self):
        """Rebuild tool message display text based on current metadata and show_output state."""
        if not self.tool_name:
            return
        
        from pico_chat.ui.tui.colors import theme
        
        # Build status line with colors
        status_parts = []
        if self.tool_status:
            # Split status by | and color each part
            parts = self.tool_status.split(' | ')
            colored_parts = []
            for part in parts:
                part = part.strip()
                if part in ['approved', 'completed']:
                    colored_parts.append(f"{theme.SUCCESS}{part}{theme.reset()}")
                elif part in ['denied', 'error']:
                    colored_parts.append(f"{theme.ERROR}{part}{theme.reset()}")
                elif part in ['executing']:
                    colored_parts.append(f"{theme.MUTED}{part}{theme.reset()}")
                else:
                    colored_parts.append(f"{theme.MUTED}{part}{theme.reset()}")
            status_parts = [' | '.join(colored_parts)]
        
        # Build header line - simpler format: "> toolname"
        header = f"{theme.WARNING}> {self.tool_name}{theme.reset()}"
        if status_parts:
            header += f" {status_parts[0]}"
        
        # Build text
        lines = [header]
        
        # Add command/args if available - extract command value directly
        if self.tool_args:
            # Try to parse as JSON to show nicely
            import json
            try:
                args_dict = json.loads(self.tool_args)
                if len(args_dict) == 1:
                    # Single arg - show the value with cmd: prefix
                    key, value = list(args_dict.items())[0]
                    if isinstance(value, str):
                        lines.append(f"{theme.MUTED}cmd:{theme.reset()} {value}")
                    else:
                        lines.append(f"{theme.MUTED}cmd:{theme.reset()} {json.dumps(value)}")
                else:
                    lines.append(f"{theme.MUTED}cmd:{theme.reset()} {json.dumps(args_dict)}")
            except:
                # Not JSON or parse error - show raw
                lines.append(f"{theme.MUTED}cmd:{theme.reset()} {self.tool_args}")
        
        # Add output if show_output is True
        if self.show_output and self.tool_output:
            lines.append(f"{theme.MUTED}out: {self.tool_output}{theme.reset()}")
        
        self.base_text = '\n'.join(lines)
        self.reformat(self.max_width)
    
    def update_metrics(self, tokens: int, tokens_per_second: float, ttft_ms: Optional[float] = None, duration_ms: Optional[float] = None):
        """Update generation metrics for this message."""
        self.metrics_tokens = tokens
        self.metrics_tokens_per_second = tokens_per_second
        if ttft_ms is not None:
            self.metrics_ttft_ms = ttft_ms
        if duration_ms is not None:
            self.metrics_duration_ms = duration_ms
        self.box.mark_changed()  # Metrics changed, affects bottom border
    
    def get_metrics_string(self) -> Optional[str]:
        """Get formatted metrics string based on config."""
        from pico_chat import pico_cfg
        
        if not pico_cfg.config.ui_show_metrics:
            return None
        
        # Only show metrics if we have data
        if self.metrics_tokens == 0 and self.metrics_tokens_per_second == 0:
            return None
        
        parts = []
        
        if pico_cfg.config.ui_metrics_show_tokens and self.metrics_tokens > 0:
            parts.append(f"{self.metrics_tokens} t")
        
        if pico_cfg.config.ui_metrics_show_speed and self.metrics_tokens_per_second > 0:
            parts.append(f"{self.metrics_tokens_per_second:.1f} t/s")
        
        if pico_cfg.config.ui_metrics_show_ttft and self.metrics_ttft_ms is not None:
            parts.append(f"ttft {self.metrics_ttft_ms:.0f}ms")
        
        return " │ ".join(parts) if parts else None
    
    def should_show_metrics(self) -> bool:
        """Check if metrics should be displayed for this message."""
        # Show if focused OR if generating (not finalized)
        return self.box.focused or not self.finalized
