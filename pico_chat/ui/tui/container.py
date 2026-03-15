from typing import List, Union, Optional
from pico_chat.ui.tui.component import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent

SizeUnit = Union[int, float, str]

class Container(Component):
    def __init__(self, children: List[Component], id: Optional[str] = None):
        super().__init__(id)
        self.children = children
        for child in self.children:
            child.parent = self

    def handle_input(self, event) -> bool:
        for child in self.children:
            if child.handle_input(event):
                return True
        return False

class Split(Container):
    def __init__(self, children: List[Component], sizes: List[SizeUnit], id: Optional[str] = None):
        """
        sizes: list of int (chars), float (0.0-1.0 for percentage), or str ("10c", "60%")
        """
        super().__init__(children, id)
        self.sizes = sizes
        if len(self.sizes) != len(self.children):
            raise ValueError("Number of sizes must match number of children")

    def _calculate_actual_sizes(self, total: int) -> List[int]:
        actual_sizes = [0] * len(self.sizes)
        remaining = total
        
        # 1. Calculate fixed sizes first
        for i, size in enumerate(self.sizes):
            if isinstance(size, int):
                actual_sizes[i] = size
                remaining -= size
            elif isinstance(size, str) and size.endswith('c'):
                val = int(size[:-1])
                actual_sizes[i] = val
                remaining -= val
        
        # 2. Calculate percentage sizes based on REMAINING space
        # (or total space? User said "100% should be constrained to what's left")
        # Let's assume percentage is of the TOTAL space but capped at remaining.
        percent_indices = []
        total_percent = 0.0
        for i, size in enumerate(self.sizes):
            if isinstance(size, float):
                percent_indices.append(i)
                total_percent += size
            elif isinstance(size, str) and size.endswith('%'):
                percent_indices.append(i)
                total_percent += float(size[:-1]) / 100.0
        
        if percent_indices:
            # If total percent > 1.0, we normalize it to 1.0
            scale = 1.0 if total_percent <= 1.0 else 1.0 / total_percent
            
            available_for_percents = max(0, remaining)
            for i in percent_indices:
                size = self.sizes[i]
                p = size if isinstance(size, float) else float(size[:-1]) / 100.0
                s = int(available_for_percents * p * scale)
                actual_sizes[i] = s
                remaining -= s

        # 3. Distribute any remaining space to "auto" components (those with size 0 or unparsed)
        auto_indices = [i for i, s in enumerate(actual_sizes) if s == 0]
        if auto_indices and remaining > 0:
            auto_size = remaining // len(auto_indices)
            for i in auto_indices:
                actual_sizes[i] = auto_size
                remaining -= auto_size
            # Add leftover pixels to the last auto component
            if remaining > 0:
                actual_sizes[auto_indices[-1]] += remaining
        
        return actual_sizes

class Vsplit(Split):
    def render(self, buffer: Buffer):
        actual_sizes = self._calculate_actual_sizes(self.width)
        curr_x = self.x
        for i, child in enumerate(self.children):
            child.set_layout(curr_x, self.y, actual_sizes[i], self.height)
            child.render(buffer)
            curr_x += actual_sizes[i]

class Hsplit(Split):
    def render(self, buffer: Buffer):
        actual_sizes = self._calculate_actual_sizes(self.height)
        
        # Identify 'auto' components (marked with 0 string, 0 int, or "auto")
        # Sizes that are percentages or fixed numbers are calculated by 
        # _calculate_actual_sizes already.
        
        # We need to refine actual_sizes for dynamic components BEFORE distributing
        # the remaining space.
        
        # 1. First, find components that WANT a specific size based on content
        for i, size in enumerate(self.sizes):
             # Only override if it wasn't a % or fixed > 0
             # Actually, if the user explicitly said "auto" or 0, we check.
             if size == 0 or size == "auto":
                 child = self.children[i]
                 if hasattr(child, 'get_preferred_height'):
                     actual_sizes[i] = child.get_preferred_height(self.width)
        
        # 2. Re-calculate the distribution for any "100%" or truly flexible parts
        # If there's a "100%", it should take whatever is left after fixed AND dynamic ones.
        total_used = sum(s for i, s in enumerate(actual_sizes) if not (isinstance(self.sizes[i], float) or (isinstance(self.sizes[i], str) and self.sizes[i].endswith('%'))))
        remaining = self.height - total_used
        
        percent_indices = [i for i, s in enumerate(self.sizes) if isinstance(s, float) or (isinstance(s, str) and s.endswith('%'))]
        if percent_indices and remaining > 0:
            for i in percent_indices:
                # Simplification: if we have 100%, it takes all remaining.
                # If multiple percents, we'd need to distribute. 
                # For pico-chat, it's usually one "100%" and one dynamic.
                actual_sizes[i] = max(0, remaining)
                # (This is basic but works for the current layout)

        curr_y = self.y
        for i, child in enumerate(self.children):
            child.set_layout(self.x, curr_y, self.width, actual_sizes[i])
            child.render(buffer)
            curr_y += actual_sizes[i]
