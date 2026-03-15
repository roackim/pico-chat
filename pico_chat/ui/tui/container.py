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

    def render(self, buffer: Buffer):
        for child in self.children:
            child.render(buffer)

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
        # 1. First, calculate fixed and percentage sizes as baseline
        actual_sizes = self._calculate_actual_sizes(self.height)
        
        # 2. Find "auto" components (0 or "auto") and get their preferred height
        total_non_auto = 0
        auto_indices = []
        for i, size in enumerate(self.sizes):
            if size == 0 or size == "auto":
                auto_indices.append(i)
                child = self.children[i]
                if hasattr(child, 'get_preferred_height'):
                    actual_sizes[i] = child.get_preferred_height(self.width)
            else:
                total_non_auto += actual_sizes[i]
        
        # 3. Handle constraints. If we have a "100%" component, it should take
        # the REMAINING space after fixed and auto components are accounted for,
        # but capped at the total height.
        
        # Identify the flexible (percentage) components
        percent_indices = [i for i, s in enumerate(self.sizes) if (isinstance(s, float) or (isinstance(s, str) and s.endswith('%')))]
        
        # Apply max_height constraints to actual_sizes BEFORE calculating percentage distribution
        for i, child in enumerate(self.children):
            if hasattr(child, 'max_height') and child.max_height:
                actual_sizes[i] = min(actual_sizes[i], child.max_height)

        if percent_indices:
            total_auto_and_fixed = sum(actual_sizes[i] for i in range(len(actual_sizes)) if i not in percent_indices)
            remaining_for_percents = max(0, self.height - total_auto_and_fixed)
            
            # For now, if there's a 100%, give it all that's left
            for i in percent_indices:
                actual_sizes[i] = remaining_for_percents

        curr_y = self.y
        for i, child in enumerate(self.children):
            final_h = actual_sizes[i]
            
            child.set_layout(self.x, curr_y, self.width, final_h)
            child.render(buffer)
            curr_y += final_h
