import os
import pathspec
# from tree_sitter import Language, Parser
# import tree_sitter_python as tspython

# # Initialize for tree-sitter 0.21.x+
# PY_LANGUAGE = Language(tspython.language())

# def extract_signatures(file_path):
#     """Extracts class and function definitions as one-liners."""
#     parser = Parser(PY_LANGUAGE)
#     try:
#         with open(file_path, 'rb') as f:
#             content = f.read()
#             tree = parser.parse(content)
        
#         query = PY_LANGUAGE.query("""
#             (class_definition name: (identifier) @name)
#             (function_definition name: (identifier) @name)
#         """)
        
#         captures = query.captures(tree.root_node)
#         signatures = []
#         for node, _ in captures:
#             # Capture only the definition line (e.g., 'def run_harness(ctx):')
#             line = node.text.decode('utf-8').split('\n')[0].strip()
#             signatures.append(line)
#         return signatures
#     except Exception:
#         return []

def get_ignore_spec(root):
    """Loads .gitignore patterns."""
    gitignore_path = os.path.join(root, '.gitignore')
    if os.path.exists(gitignore_path):
        with open(gitignore_path, 'r') as f:
            return pathspec.PathSpec.from_lines('gitwildmatch', f)
    return pathspec.PathSpec.from_lines('gitwildmatch', [])

def build_harness_context(root):
    """Generates a flattened, path-explicit project skeleton.
    
    This function walks the project structure, respecting .gitignore,
    and produces a concise textual representation of the file tree
    and key symbol signatures to give the LLM context about the project.
    """
    spec = get_ignore_spec(root)
    context_output = []

    context_output.append(f"Project Files (filtered by .gitignore):")
    for dirpath, dirnames, filenames in os.walk(root):
        # 1. Prune dot-folders and ignored directories in-place
        dirnames[:] = [d for d in dirnames if not d.startswith('.') 
                       and not spec.match_file(os.path.relpath(os.path.join(dirpath, d), root))]

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
