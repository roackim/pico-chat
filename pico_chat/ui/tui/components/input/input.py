from typing import Optional, Any, List, Callable
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.menu import SelectionMenu
from pico_chat.ui.tui.fuzzy import fuzzy_search
from .text_buffer import TextBuffer
from .coordinate_mapper import CoordinateMapper
from .input_handlers import (
    InputHandler, InputContext, KeyboardHandler, MouseHandler, PasteHandler
)
from .scroll_manager import ScrollManager
from .cursor_renderer import CursorRenderer
from .command_completion import CommandCompletion
from .subcommand_completion import SubcommandCompletion
from .context_completion import ContextCompletion
from .server_completion import ServerCompletion
from .path_completion import PathCompletion
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent
from pico_chat.ui.tui.layout_utils import display_width

from pico_chat.ui.tui.colors import theme

class InputComponent(Component):
    """Multi-line text input component with menus, scrolling, and cursor animation."""
    
    def __init__(self, prompt: str = "> ", id: Optional[str] = None, frame_color=None, content_color=None):
        super().__init__(id)
        self.prompt = prompt
        self.frame_color = frame_color if frame_color is not None else theme.DEFAULT
        self.content_color = content_color if content_color is not None else theme.DEFAULT
        self.bg = theme.get_bg()  # Use global background
        self.config = None  # Config object passed during initialization
        self.focused = True  # Track focus state for input handling and cursor rendering
        
        # Core components
        self.buffer = TextBuffer()
        self.coord_mapper = CoordinateMapper(prompt, self.width)
        self.scroll_manager = ScrollManager(
            self.buffer,
            self.coord_mapper,
            lambda: self.height
        )
        self.cursor_renderer = CursorRenderer(lambda: self.config)
        
        # Input handlers
        self.keyboard_handler = KeyboardHandler()
        self.input_handlers: List[InputHandler] = [
            PasteHandler(),
            MouseHandler(),
            self.keyboard_handler
        ]
        
        # Completion system (lazy-initialized)
        self.command_completion: Optional[CommandCompletion] = None
        self.command_list: List[str] = []
        self.subcommand_completion: Optional[SubcommandCompletion] = None
        self.subcommand_callback: Optional[Callable[[str], List[str]]] = None
        self.context_completion: Optional[ContextCompletion] = None
        self.context_items_callback: Optional[Callable[[], List[str]]] = None
        self.server_completion: Optional[ServerCompletion] = None
        self.server_names_callback: Optional[Callable[[], List[str]]] = None
        self.path_completion: Optional[PathCompletion] = None
        self.path_commands: List[str] = []
        self.get_workspace_callback: Optional[Callable[[], str]] = None
    
    @property
    def on_submit(self):
        """Get submit callback."""
        return self.keyboard_handler.on_submit
    
    @on_submit.setter
    def on_submit(self, callback):
        """Set submit callback."""
        self.keyboard_handler.on_submit = callback
    
    @property
    def text(self) -> str:
        """Get current text (for backward compatibility)."""
        return self.buffer.text
    
    @text.setter
    def text(self, value: str):
        """Set text (for backward compatibility)."""
        self.buffer.text = value
        # Mark parent for re-render
        if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'mark_changed'):
            self.parent.mark_changed()
    
    @property
    def cursor_pos(self) -> int:
        """Get cursor position (for backward compatibility)."""
        return self.buffer.cursor_pos
    
    @cursor_pos.setter
    def cursor_pos(self, value: int):
        """Set cursor position (for backward compatibility)."""
        self.buffer.cursor_pos = value
    
    def setup_commands(self, commands: List[str]):
        """Initialize command completion system."""
        self.command_list = commands
    
    def setup_subcommands(self, get_subcommands_callback: Callable[[str], List[str]]):
        """Initialize subcommand completion system."""
        self.subcommand_callback = get_subcommands_callback
    
    def setup_context(self, get_items_callback: Callable[[], List[str]]):
        """Initialize context (@file) completion system."""
        self.context_items_callback = get_items_callback
    
    def setup_servers(self, get_servers_callback: Callable[[], List[str]]):
        """Initialize server name completion system."""
        self.server_names_callback = get_servers_callback

    def setup_path_commands(self, commands: List[str], get_workspace: Callable[[], str]):
        """Initialize filesystem path completion for the given commands."""
        self.path_commands = commands
        self.get_workspace_callback = get_workspace
    
    def _ensure_command_menu(self):
        """Lazy-create command menu and completion system on first use."""
        if self.command_completion is None and self.command_list:
            compositor = self.compositor_ref if hasattr(self, 'compositor_ref') else None
            menu = SelectionMenu(
                compositor=compositor,
                frame_color=self.content_color,
                content_color=self.content_color
            )
            self.command_completion = CommandCompletion(menu, self.command_list)
    
    def _ensure_subcommand_menu(self):
        """Lazy-create subcommand menu and completion system on first use."""
        if self.subcommand_completion is None and self.subcommand_callback:
            compositor = self.compositor_ref if hasattr(self, 'compositor_ref') else None
            menu = SelectionMenu(
                compositor=compositor,
                frame_color=self.content_color,
                content_color=self.content_color
            )
            self.subcommand_completion = SubcommandCompletion(menu, self.subcommand_callback)
    
    def _ensure_context_menu(self):
        """Lazy-create context menu and completion system on first use."""
        if self.context_completion is None and self.context_items_callback:
            compositor = self.compositor_ref if hasattr(self, 'compositor_ref') else None
            menu = SelectionMenu(
                compositor=compositor,
                frame_color=self.content_color,
                content_color=self.content_color
            )
            self.context_completion = ContextCompletion(menu, self.context_items_callback)
    
    def _ensure_server_menu(self):
        """Lazy-create server menu and completion system on first use."""
        if self.server_completion is None and self.server_names_callback:
            compositor = self.compositor_ref if hasattr(self, 'compositor_ref') else None
            menu = SelectionMenu(
                compositor=compositor,
                frame_color=self.content_color,
                content_color=self.content_color
            )
            self.server_completion = ServerCompletion(menu, self.server_names_callback)

    def _ensure_path_menu(self):
        """Lazy-create path menu and completion system on first use."""
        if self.path_completion is None and self.path_commands and self.get_workspace_callback:
            compositor = self.compositor_ref if hasattr(self, 'compositor_ref') else None
            menu = SelectionMenu(
                compositor=compositor,
                frame_color=self.content_color,
                content_color=self.content_color
            )
            self.path_completion = PathCompletion(menu, self.path_commands, self.get_workspace_callback)

    # def setup_menus(self, commands: List[str], get_context_items: Optional[Callable[[], List[str]]] = None,
                    # get_subcommands: Optional[Callable[[str], List[str]]] = None):
        # """Initialize menu data sources."""
        # self.command_list = commands
        # self.get_context_items_callback = get_context_items
        # self.get_subcommands_callback = get_subcommands
    
    def set_compositor(self, compositor):
        """Set compositor reference for overlay rendering."""
        self.compositor_ref = compositor
    
    def _on_text_changed(self):
        """Called whenever text changes - updates completion menus and marks parent for re-render."""
        # Mark parent Box as changed for visual update
        if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'mark_changed'):
            self.parent.mark_changed()
        
        # Try command completion first (has priority at line start, no space)
        if self.command_list:
            self._ensure_command_menu()
            self.command_completion.update(self.buffer.text, self.buffer.cursor_pos)
            
            if self.command_completion.is_active:
                # Command menu is active - hide others and position
                if self.subcommand_completion:
                    self.subcommand_completion.hide()
                if self.context_completion:
                    self.context_completion.hide()
                if self.server_completion:
                    self.server_completion.hide()
                self._position_command_menu()
                return
        
        # Try subcommand completion (if command has space)
        if self.subcommand_callback:
            self._ensure_subcommand_menu()
            self.subcommand_completion.update(self.buffer.text, self.buffer.cursor_pos)
            
            if self.subcommand_completion.is_active:
                # Subcommand menu is active - hide others and position
                if self.context_completion:
                    self.context_completion.hide()
                if self.server_completion:
                    self.server_completion.hide()
                self._position_subcommand_menu()
                return
        
        # Try server completion (more specific than context)
        if self.server_names_callback:
            self._ensure_server_menu()
            self.server_completion.update(self.buffer.text, self.buffer.cursor_pos)
            
            if self.server_completion.is_active:
                if self.context_completion:
                    self.context_completion.hide()
                self._position_server_menu()
                return
        
        # Try path completion (e.g. /cd)  
        if self.get_workspace_callback:
            self._ensure_path_menu()
            self.path_completion.update(self.buffer.text, self.buffer.cursor_pos)

            if self.path_completion.is_active:
                if self.context_completion:
                    self.context_completion.hide()
                self._position_path_menu()
                return

        # Try context completion if no other menu active
        if self.context_items_callback:
            self._ensure_context_menu()
            self.context_completion.update(self.buffer.text, self.buffer.cursor_pos)
            
            if self.context_completion.is_active:
                self._position_context_menu()
                return
    
    def _position_command_menu(self):
        """Position command menu at the '/' character."""
        if not self.command_completion or not self.command_completion.is_active:
            return
        
        text = self.buffer.text.lstrip()
        leading_ws = len(self.buffer.text) - len(text)
        trigger_pos = leading_ws  # Position of '/'
        
        self._position_menu_at(self.command_completion.menu, trigger_pos)
    
    def _position_subcommand_menu(self):
        """Position subcommand menu at the subcommand text location."""
        if not self.subcommand_completion or not self.subcommand_completion.is_active:
            return
        
        text = self.buffer.text.lstrip()
        leading_ws = len(self.buffer.text) - len(text)
        
        # Find position of space after command
        if ' ' in text:
            space_pos = text.find(' ')
            trigger_pos = leading_ws + space_pos + 1  # +1 to skip space
        else:
            trigger_pos = leading_ws
        
        self._position_menu_at(self.subcommand_completion.menu, trigger_pos)
    
    def _position_server_menu(self):
        """Position server menu at the server name location."""
        if not self.server_completion or not self.server_completion.is_active:
            return
        
        text = self.buffer.text.lstrip()
        leading_ws = len(self.buffer.text) - len(text)
        
        # Find position after '/server use ' or '/server remove '
        if text.startswith('/server '):
            parts = text.split(' ', 2)
            if len(parts) >= 2:
                # Position after the subcommand
                pos_after_server = text.find(' ') + 1
                pos_after_subcommand = text.find(' ', pos_after_server) + 1 if ' ' in text[pos_after_server:] else pos_after_server
                trigger_pos = leading_ws + pos_after_subcommand
            else:
                trigger_pos = leading_ws
        else:
            trigger_pos = leading_ws
        
        self._position_menu_at(self.server_completion.menu, trigger_pos)
    
    def _position_path_menu(self):
        """Position path menu after the command and space (e.g. '/cd ')."""
        if not self.path_completion or not self.path_completion.is_active:
            return

        text = self.buffer.text.lstrip()
        leading_ws = len(self.buffer.text) - len(text)

        # Position after "/<cmd> "
        if ' ' in text:
            trigger_pos = leading_ws + text.find(' ') + 1
        else:
            trigger_pos = leading_ws

        self._position_menu_at(self.path_completion.menu, trigger_pos)

    def _position_context_menu(self):
        """Position context menu at the '@' character."""
        if not self.context_completion or not self.context_completion.is_active:
            return
        
        trigger_pos = self.context_completion.find_trigger_position(
            self.buffer.text, self.buffer.cursor_pos
        )
        if trigger_pos is not None:
            self._position_menu_at(self.context_completion.menu, trigger_pos)
    
    def _position_menu_at(self, menu, trigger_pos: int):
        """Position menu at specific text position (shared logic)."""
        # Calculate screen position
        trigger_row, trigger_col = self.coord_mapper.get_cursor_coords(
            self.buffer.text, trigger_pos
        )
        
        scroll_y = self.scroll_manager.scroll_y
        
        # Position menu above trigger
        visible_count = min(len(menu.items), menu.max_height - 2)
        menu_height = visible_count + 2
        
        menu_x = self.x + trigger_col - 2  # 2-char offset
        menu_y = self.y + trigger_row - scroll_y - menu_height
        
        available_width = self.width - (trigger_col - 2)
        menu_width = max(available_width, 20)
        
        menu.set_layout(menu_x, menu_y, menu_width, menu_height)
    

    def set_layout(self, x: int, y: int, width: int, height: int):
        """Update layout and notify coordinate mapper of width change."""
        super().set_layout(x, y, width, height)
        self.coord_mapper.update_dimensions(width)

    def get_preferred_height(self, width: int) -> int:
        """Calculate height needed for wrapped text."""
        # Temporarily update dimensions for calculation
        old_width = self.coord_mapper.width
        self.coord_mapper.update_dimensions(width)
        lines = self.coord_mapper.get_wrapped_lines(self.buffer.text)
        self.coord_mapper.update_dimensions(old_width)
        
        # Apply maximum height constraint from config
        height = len(lines) if lines else 1
        if self.config and hasattr(self.config, 'ui_max_input_height'):
            height = min(height, self.config.ui_max_input_height)
        return height
    
    def is_cursor_on_first_line(self) -> bool:
        """Check if the cursor is on the first line of text (regardless of scroll position).
        
        Returns True only if the cursor is on row 0 of the actual text content,
        not just the first visible line if the input is scrolled.
        """
        cursor_row, _ = self.coord_mapper.get_cursor_coords(
            self.buffer.text, self.buffer.cursor_pos
        )
        return cursor_row == 0
    
    def set_focused(self, focused: bool):
        """Set the focused state of this input component."""
        self.focused = focused

    def render(self, buffer: Buffer):
        """Render the input field with prompt, text, and scrolling (cursor rendered separately)."""
        # Clear background
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=self.bg)
        
        # Get wrapped lines
        lines = self.coord_mapper.get_wrapped_lines(self.buffer.text)
        prompt_width = display_width(self.prompt)
        
        # Ensure cursor is visible and scroll is constrained
        self.scroll_manager.ensure_cursor_visible()
        
        # Render visible lines
        scroll_y = self.scroll_manager.scroll_y
        
        # Safety check: ensure scroll_y is in bounds
        if scroll_y >= len(lines):
            scroll_y = max(0, len(lines) - 1)
            self.scroll_manager.scroll_y = scroll_y
        
        for i in range(scroll_y, min(len(lines), scroll_y + self.height)):
            line_idx = i - scroll_y
            line = lines[i]
            
            # Only add prompt to the very first line of content (when not scrolled past it)
            if i == 0:
                # First line of text - add prompt
                display_line = self.prompt + line
            else:
                # Continuation lines already have proper padding
                display_line = line
            
            buffer.write_str(self.x, self.y + line_idx, display_line, fg=self.content_color, bg=self.bg, max_width=self.width)
        
        # Note: Cursor is rendered separately via render_cursor() called after SubBuffer blit
        
        # Render parameter hints in grey after cursor
        if self.focused and not self.has_active_completion():
            hint = self._get_parameter_hint()
            if hint:
                # Get cursor screen position
                cursor_row, cursor_col = self.coord_mapper.get_cursor_coords(self.buffer.text, self.buffer.cursor_pos)
                # Adjust for scroll
                screen_row = cursor_row - scroll_y
                
                # Only show hint if cursor is visible
                if 0 <= screen_row < self.height:
                    hint_x = self.x + cursor_col
                    hint_y = self.y + screen_row
                    
                    # Show hint in muted color (limited to available width)
                    hint_max_width = max(0, self.width - cursor_col)
                    buffer.write_str(hint_x, hint_y, hint, fg=theme.MUTED, bg=self.bg, max_width=hint_max_width)
        
        # Menu is rendered by compositor as overlay (not here)
    
    def _get_parameter_hint(self) -> str:
        """Get parameter hint text to show in grey after cursor."""
        text = self.buffer.text.lstrip()
        
        # Only show hints for commands
        if not text.startswith('/'):
            return ""
        
        # Parse command structure (strip trailing spaces to handle "/server use " case)
        parts = [p for p in text.split(' ') if p]  # Filter out empty parts from trailing spaces
        
        # /server add hints
        if len(parts) >= 2 and parts[0] == '/server' and parts[1] == 'add':
            if len(parts) == 2:
                return " openrouter|llamacpp"
            elif len(parts) == 3:
                server_type = parts[2]
                if server_type == 'openrouter':
                    return " MODEL_ID [NAME] [PROVIDER]"
                elif server_type == 'llamacpp':
                    return " URL [NAME]"
            elif len(parts) == 4:
                server_type = parts[2]
                if server_type == 'openrouter':
                    return " [NAME] [PROVIDER]"
                elif server_type == 'llamacpp':
                    return " [NAME]"
            elif len(parts) == 5:
                server_type = parts[2]
                if server_type == 'openrouter':
                    return " [PROVIDER]"
        
        # /server use/remove hints (though these have completion)
        elif len(parts) >= 2 and parts[0] == '/server' and parts[1] in ('use', 'remove'):
            if len(parts) == 2:
                return " SERVER_NAME"
        
        # /set hints
        elif len(parts) >= 2 and parts[0] == '/set':
            if len(parts) == 2:
                return " fps"
            elif parts[1] == 'fps' and len(parts) == 2:
                return " 30|60|120"
        
        return ""
    
    def render_cursor(self, buffer: Buffer):
        """Render cursor as an overlay (called outside SubBuffer caching).
        
        This is called by Box after blitting SubBuffer to main buffer,
        ensuring cursor blinks even when content hasn't changed.
        """
        if not self.focused:
            return
        
        # Get cursor position
        cursor_row, cursor_col = self.coord_mapper.get_cursor_coords(
            self.buffer.text, self.buffer.cursor_pos
        )
        
        scroll_y = self.scroll_manager.scroll_y
        
        # Render cursor and let it mark parent if it blinked
        self.cursor_renderer.render(
            buffer, cursor_row, cursor_col,
            self.x, self.y, scroll_y, self.height,
            parent_box=self.parent
        )

    def _accept_completion(self, completion, add_space=False) -> bool:
        """Generic completion acceptance handler.
        
        Args:
            completion: The completion object to accept
            add_space: Whether to add a trailing space after completion
            
        Returns:
            True if completion was accepted, False otherwise
        """
        if isinstance(completion, ContextCompletion):
            result = completion.accept_selection(self.buffer.text, self.buffer.cursor_pos)
            if result:
                new_text, new_cursor_pos = result
                if add_space:
                    self.buffer.text = new_text + " "
                    self.buffer.cursor_pos = len(self.buffer.text)
                else:
                    self.buffer.text = new_text
                    self.buffer.cursor_pos = new_cursor_pos
                completion.hide()
                if add_space:
                    self._on_text_changed()
                return True
        else:
            # Generic pattern for Command, Subcommand, and Server completions
            completed = completion.accept_selection(self.buffer.text)
            if completed:
                if add_space:
                    self.buffer.text = completed + " "
                    self.buffer.cursor_pos = len(self.buffer.text)
                else:
                    self.buffer.text = completed
                    self.buffer.cursor_pos = len(completed)
                completion.hide()
                if add_space:
                    self._on_text_changed()
                return True
        return False

    def has_active_completion(self) -> bool:
        """Return True when any completion menu is currently active."""
        return any(
            completion and completion.is_active
            for completion in (
                self.command_completion,
                self.subcommand_completion,
                self.context_completion,
                self.server_completion,
                self.path_completion,
            )
        )

    def handle_input(self, event: Any) -> bool:
        """Handle input events by delegating to appropriate handlers."""
        # Ignore keyboard input if not focused (but allow mouse events for potential focus change)
        if not self.focused and not isinstance(event, MouseEvent):
            return False
        
        # Mark input for cursor animation
        self.cursor_renderer.mark_input()
        
        # Determine which completion is active (generic iteration)
        active_completion = None
        for completion in [
            self.command_completion,
            self.subcommand_completion,
            self.server_completion,
            self.path_completion,
            self.context_completion,
        ]:
            if completion and completion.is_active:
                active_completion = completion
                break
        
        # Handle ESC - cancel menu and remember the word
        if event == '\x1b':  # ESC key
            if active_completion:
                active_completion.cancel(self.buffer.text, self.buffer.cursor_pos)
                return True
            return False  # Let other handlers try if menu not active
        
        # Handle arrow keys for menu navigation (priority)
        if active_completion:
            if event == '\x1b[A':  # Up arrow
                active_completion.navigate_up()
                return True
            elif event == '\x1b[B':  # Down arrow
                active_completion.navigate_down()
                return True
        
        # Handle Tab - accept selection with trailing space
        if event == '\t':
            if active_completion and self._accept_completion(active_completion, add_space=True):
                return True
            return False  # Let other handlers try
        
        # Handle Enter - accept selection + submit (no trailing space)
        if event in ('\r', '\n'):
            # Try completion first if menu is visible
            if active_completion:
                self._accept_completion(active_completion, add_space=False)
            

        
        # Handle mouse events (check bounds)
        if isinstance(event, MouseEvent):
            # Only handle clicks within this component's bounds
            if not (self.x <= event.x < self.x + self.width and
                    self.y <= event.y < self.y + self.height):
                return False
        
        # Create context for handlers (no menu_manager needed)
        context = InputContext(
            self.buffer,
            self.coord_mapper,
            self.scroll_manager,
            None  # menu_manager is removed
        )
        
        # Try each handler
        for handler in self.input_handlers:
            if handler.can_handle(event) and handler.handle(event, context):
                # Update menu visibility after text changes
                self._on_text_changed()
                return True
        
        return False

    def update(self, text: str):
        """Update the input field text programmatically."""
        self.buffer.text = text
        self.buffer.cursor_pos = len(text)
        # Mark parent for re-render
        if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'mark_changed'):
            self.parent.mark_changed()

    def clear(self):
        """Clear the input field."""
        self.buffer.clear()
        self.scroll_manager.reset()
        # Mark parent for re-render
        if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'mark_changed'):
            self.parent.mark_changed()
