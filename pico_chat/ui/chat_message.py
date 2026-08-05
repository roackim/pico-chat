"""Chat message representation with formatting and action support."""

from typing import Optional
from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme, RGB
from pico_chat.ui.tui.components import TextComponent, Box
from pico_chat.ui.tui.components.markdown import MarkdownComponent
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
                 render_markdown: bool = False,
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
            render_markdown: If True, use MarkdownComponent instead of TextComponent
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
        self.layout_revision = 0
        self.left_pad = left_pad
        self.right_pad = right_pad
        self.title = title
        self.frame_color = frame_color
        self.left_margin = left_margin
        self.right_margin = right_margin
        self.render_markdown = render_markdown

        if render_markdown:
            self.formatted_text = ""  # Not used for markdown messages
            self.component = MarkdownComponent(text, fg=content_color, left_pad=left_pad)
        else:
            self.formatted_text = self._format_line_wrap()
            self.component = TextComponent(self.formatted_text, fg=content_color)

        self.finalized = False  # Whether this message is finalized
        
        # Tool-specific metadata
        self.tool_name: Optional[str] = None
        self.tool_args: Optional[str] = None
        self.tool_output: Optional[str] = None
        self.tool_status: Optional[str] = None  # "approved", "denied", "completed", etc.
        self.show_output: bool = False  # Toggle for output visibility (press 'o' to show out: line)

        # Steering / queue state
        self.is_queued: bool = False   # UserMsg waiting while generation is active
        self.is_paused: bool = False   # PicoMsg/ThinkingMsg cancelled via pause action
        
        # Generation metrics
        self.metrics_tokens: int = 0
        self.metrics_tokens_per_second: float = 0.0
        self.metrics_ttft_ms: Optional[float] = None
        self.metrics_duration_ms: Optional[float] = None
        
        # Command error context (for edit action on failed commands)
        self.command_text: Optional[str] = None
        
        # Action click flash feedback (set by ChatHistoryPanel, read by Box)
        self._flash_action_key: Optional[str] = None
        
        self.box = Box(
            self.component,
            parent_msg=self,
            compact_when_unfocused=isinstance(msg_type, msg_types.ToolCallMsg)
        )
    
    def finalize(self):
        self.finalized = True
        self.box.mark_changed()  # Finalization affects actions display
    
    def get_active_actions(self):
        """Get the list of active actions based on message state."""
        actions = list(self.type.actions)

        if isinstance(self.type, msg_types.UserMsg):
            # STEER only visible while this message is sitting in the queue
            if not self.is_queued:
                actions = [a for a in actions if a != MsgAction.STEER]

        elif isinstance(self.type, msg_types.PicoMsg):  # includes ThinkingMsg
            if self.is_paused:
                # Paused: copy, edit prefill, resume, delete
                keep = {MsgAction.COPY, MsgAction.EDIT, MsgAction.RESUME, MsgAction.DELETE}
                actions = [a for a in actions if a in keep]
            elif self.finalized:
                # Finalized: hide streaming-only actions
                actions = [a for a in actions if a not in (
                    MsgAction.STOP, MsgAction.PAUSE, MsgAction.RESUME
                )]
                # Only ThinkingMsg makes sense to edit as a thinking prefill
                if not isinstance(self.type, msg_types.ThinkingMsg):
                    actions = [a for a in actions if a != MsgAction.EDIT]
            else:
                # Live streaming: hide destructive/post-gen actions
                actions = [a for a in actions if a not in (
                    MsgAction.EDIT, MsgAction.DELETE, MsgAction.RETRY, MsgAction.RESUME
                )]

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

    def _is_markdown(self) -> bool:
        """Check if this message uses markdown rendering."""
        return self.render_markdown
    
    def set_focused(self, focused: bool):
        """Set the focused state of this message."""
        # Focus can change the preferred height of compact messages (for
        # example tool/permission messages expand from one line to a box with
        # borders).  Make the history panel discard its height-cache entry so
        # the newly focused single-line message receives a real layout.
        if self.box.focused != focused:
            self.layout_revision += 1
        self.box.set_focused(focused)
    
    def _format_line_wrap(self) -> str:
        """Format the message text with smart word wrapping and padding.
        
        Uses the provided left and right padding for each line.
        Normalises the text first: strips trailing whitespace on every line
        and collapses runs of blank lines into a single blank line so that
        streaming artefacts (extra \\n from chunk boundaries) don't bloat
        the display.  Existing intentional newlines are preserved.
        """
        if self.max_width is None or self.max_width <= 0:
            return self.base_text
        
        # Calculate available width for content after padding
        content_width = self.max_width - self.left_pad - self.right_pad
        if content_width < 1:
            content_width = 1
        
        # Convert literal \n escape sequences to real newlines (thinking messages)
        base_text = self.base_text.replace('\\n', '\n')
        
        # Strip trailing newlines from the whole block
        base_text = base_text.rstrip('\n')
        
        # Split into raw lines
        raw_lines = base_text.split('\n')
        
        # Normalise: strip trailing whitespace from each line, collapse
        # consecutive blank lines into one, and remove trailing blank lines.
        normalised: list[str] = []
        for line in raw_lines:
            stripped = line.rstrip()
            # Collapse multiple consecutive blank lines into a single one
            if not stripped and normalised and normalised[-1] == "":
                continue
            normalised.append(stripped)
        
        # Strip trailing blank lines
        while normalised and normalised[-1] == "":
            normalised.pop()
        
        # Wrap each normalised line and apply padding
        lines = []
        for line in normalised:
            if not line:
                lines.append("")
                continue
            
            wrapped = wrap_text(line, content_width, padding_width=0, first_line_padding=False)
            for w_line in wrapped.split('\n'):
                lines.append(" " * self.left_pad + w_line)
        
        return "\n".join(lines)
    
    def reformat(self, max_width: int) -> str:
        """Reformat the message with a new maximum width.

        Args:
            max_width: New maximum width for line wrapping

        Returns:
            The newly formatted text (plain-text fallback for markdown)
        """
        self.max_width = max_width
        self.layout_revision += 1

        if self._is_markdown():
            # MarkdownComponent handles wrapping internally via set_layout / width
            self.component.update(self.base_text)
            self.box.mark_changed()
            return self.base_text
        else:
            self.formatted_text = self._format_line_wrap()
            self.component.update(self.formatted_text)
            self.box.mark_changed()
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
        self.base_text += text
        self.reformat(self.max_width)
    
    def rebuild_tool_display(self):
        """Rebuild tool message display text based on current metadata and show_output state."""
        if not self.tool_name:
            return
        
        from pico_chat.ui.tui.colors import theme
        
        # Build status line with colors - use symbols for compact display
        status_parts = []
        status_symbol = ""
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
                elif part in ['executing', 'drafting']:
                    colored_parts.append(f"{theme.MUTED}{part}{theme.reset()}")
                else:
                    colored_parts.append(f"{theme.MUTED}{part}{theme.reset()}")
            status_parts = [' | '.join(colored_parts)]
            
            # For compact mode, use a simple symbol
            if 'completed' in self.tool_status:
                status_symbol = f" {theme.SUCCESS}✓{theme.reset()}"
            elif 'error' in self.tool_status or 'denied' in self.tool_status:
                status_symbol = f" {theme.ERROR}✗{theme.reset()}"
            elif 'executing' in self.tool_status:
                status_symbol = f" {theme.MUTED}⋯{theme.reset()}"
        
        # Build header line - use "?" prefix for permission requests, ">" for tool calls
        from pico_chat.ui.tui import msg_types
        if isinstance(self.type, msg_types.AskPermissionMsg):
            header = f"{theme.PERMISSION}? {self.tool_name}{theme.reset()}"
        else:
            header = f"{theme.WARNING}> {self.tool_name}{theme.reset()}"
        
        # Add compact arg summary to header for better single-line view
        args_summary = ""
        if self.tool_args:
            import json
            try:
                args_dict = json.loads(self.tool_args)
                # Extract key info for compact display
                if self.tool_name == "patch" and isinstance(args_dict, dict):
                    path = args_dict.get("path")
                    if path:
                        args_summary = f" {theme.MUTED}{path}{theme.reset()}"
                elif len(args_dict) == 1:
                    # Single arg - show value (truncate if too long)
                    key, value = list(args_dict.items())[0]
                    if isinstance(value, str):
                        # Truncate long values
                        if len(value) > 60:
                            value = value[:57] + "..."
                        args_summary = f" {theme.MUTED}{value}{theme.reset()}"
                    else:
                        args_summary = f" {theme.MUTED}{json.dumps(value)[:60]}{theme.reset()}"
            except:
                pass
        
        # Check if we're in compact mode for status display
        # Compact when unfocused only
        is_compact = self.box.compact_when_unfocused and not self.box.focused
        
        header += args_summary
        if is_compact:
            # Compact: just show symbol
            header += status_symbol
        else:
            # Expanded: show full status text
            if status_parts:
                header += f" {status_parts[0]}"
        
        # Build text
        lines = [header]
        
        # Add command/args if available - extract command value directly (skip in compact mode)
        if self.tool_args and not is_compact:
            # Try to parse as JSON to show nicely
            import json
            import re
            try:
                args_dict = json.loads(self.tool_args)
                
                if self.tool_name == "patch" and isinstance(args_dict, dict):
                    patch_lines = 0
                    path = args_dict.get("path")
                    if "patch_content" in args_dict:
                        patch_content = args_dict.get("patch_content")
                        if isinstance(patch_content, str) and patch_content:
                            patch_lines = len(patch_content.splitlines())
                    elif "replace" in args_dict:
                        replace_content = args_dict.get("replace")
                        if isinstance(replace_content, str) and replace_content:
                            patch_lines = len(replace_content.splitlines())
                    if path:
                        lines.append(f"{theme.MUTED}cmd:{theme.reset()} {path} ({patch_lines} lines)")
                    else:
                        lines.append(f"{theme.MUTED}cmd:{theme.reset()} {patch_lines} lines")
                elif len(args_dict) == 1:
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
        
        # Add output if show_output is True (toggle with 'o' key)
        if self.show_output and self.tool_output and not is_compact:
            # Split output into lines and format each one
            output_lines = self.tool_output.split('\n')
            for i, line in enumerate(output_lines):
                if i == 0:
                    lines.append(f"{theme.MUTED}out:{theme.reset()} {line}")
                else:
                    lines.append(f"     {line}")  # Indent continuation lines
        
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
