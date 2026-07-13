import os
import pathspec
from pathlib import Path
from typing import Dict, List
from datetime import date, datetime

def is_git_repo(root) -> bool:
    """Returns True if root (or any parent) contains a .git directory."""
    path = Path(root).resolve()
    for candidate in [path, *path.parents]:
        if (candidate / '.git').exists():
            return True
    return False

def get_ignore_spec(root):
    """Loads .gitignore patterns."""
    gitignore_path = os.path.join(root, '.gitignore')
    if os.path.exists(gitignore_path):
        with open(gitignore_path, 'r') as f:
            return pathspec.PathSpec.from_lines('gitwildmatch', f)
    return pathspec.PathSpec.from_lines('gitwildmatch', [])

def build_tree_structure(root: str, spec) -> Dict:
    """Build a nested dictionary representing the file tree."""
    tree = {}
    
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune dot-folders and ignored directories
        dirnames[:] = [d for d in dirnames if not d.startswith('.') 
                       and not spec.match_file(os.path.relpath(os.path.join(dirpath, d), root))]
        
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == '.':
            current = tree
        else:
            # Navigate to the correct position in the tree
            parts = rel_dir.split(os.sep)
            current = tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        
        # Add files
        for filename in sorted(filenames):
            if filename.startswith('.'):
                continue
            
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root)
            
            if spec.match_file(rel_path):
                continue
            
            current[filename] = None  # None indicates a file (not a directory)
    
    return tree

def format_tree(tree: Dict, prefix: str = "") -> List[str]:
    """Format tree structure with proper indentation."""
    lines = []
    items = sorted(tree.items(), key=lambda x: (x[1] is None, x[0]))  # Dirs first, then files
    
    for i, (name, subtree) in enumerate(items):
        is_last = (i == len(items) - 1)
        
        # Determine the connector for this item
        connector = "└── " if is_last else "├── "
        
        if subtree is None:
            # It's a file
            lines.append(f"{prefix}{connector}{name}")
        else:
            # It's a directory
            lines.append(f"{prefix}{connector}{name}/")
            
            # Determine the prefix for children based on parent's position
            extension = "    " if is_last else "│   "
            child_prefix = prefix + extension
            
            # Recurse into subdirectory
            lines.extend(format_tree(subtree, child_prefix))
    
    return lines

def build_harness_context(root, format: str = None):
    """Generates a project skeleton in either tree or flat format.
    
    This function walks the project structure, respecting .gitignore,
    and produces a concise textual representation of the file tree
    and key symbol signatures to give the LLM context about the project.
    
    Args:
        root: Project root directory
        format: "tree" or "flat". If None, uses pico_cfg.config.context_format
    """
    # Import here to avoid circular dependency
    if format is None:
        from pico_chat import pico_cfg
        format = pico_cfg.config.context_format
    

    
    if not is_git_repo(root):
        return f"Project Root: {root}\n[WARNING: Not a git repository — file tree skipped]"

    spec = get_ignore_spec(root)
    context_output = []
    
    # Add current time and date metadata
    cdate = datetime.now().date()
    ctime = datetime.now().strftime("%H:%M:%S")  # format to HH:MM:SS
    
    context_output.append(f"Current date: {cdate}")
    context_output.append(f"Current time: {ctime}")
    context_output.append("")  # Blank line for separation
    context_output.append(f"Project Root: {root}")
    
    if format == "tree":
        context_output.append("Files (tree format, filtered by .gitignore):")
        tree = build_tree_structure(root, spec)
        tree_lines = format_tree(tree)
        context_output.extend(tree_lines)
    else:  # flat format
        context_output.append(f"Files (filtered by .gitignore):")
        for dirpath, dirnames, filenames in os.walk(root):
            # 1. Prune dot-folders and ignored directories in-place
            dirnames[:] = [d for d in dirnames if not d.startswith('.') 
                           and not spec.match_file(os.path.relpath(os.path.join(dirpath, d), root))]

            for dirname in sorted(dirnames):
                full_path = os.path.join(dirpath, dirname)
                rel_path = os.path.relpath(full_path, root)
                context_output.append(f"{rel_path}/")

            for filename in sorted(filenames):
                # 2. Skip dot-files (except .gitignore if needed)
                if filename.startswith('.'):
                    continue
                
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, root)
                
                # 3. Final check against .gitignore for files
                if spec.match_file(rel_path):
                    continue

                # 4. Format output for LLM consumption
                context_output.append(f"{rel_path}")
                
                # # 5. Add signatures for supported source files
                # if filename.endswith('.py'):
                #     signatures = extract_signatures(full_path)
                #     for sig in signatures:
                #         # Indent signatures for hierarchy visualization
                #         context_output.append(f"  SYMB: {sig} ...")

    return "\n".join(context_output)
