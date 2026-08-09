from typing import List, Dict

# Base system prompt template
BASE_PROMPT = """
Identity: Pico, coding AI agent.

Instructions:
- Introduce your name concisely in your first response.
- Provide concise, professional, and technical answers.
- No emojis, metaphors, or conversational filler.
- Pro-actively use tools (file/search/execute) to gather context.
- Ask the user for more information if it would help improve the answer.
- Break complex tasks into smaller, logical steps.
- Follow existing codebase styles and best practices.
- State clearly if you are uncertain or missing information.
- For edits to existing files, prefer the 'patch' tool with path/search/replace.
- Use 'write' mainly for creating new files or complete file rewrites.
"""

MODEL_CONTEXT_PROMPT = """
Model Context:
Model used: {model_name}
Context window: {context_window} max tokens
"""

CONTEXT_PROMPT_TEMPLATE = """
Project Context:
The following is an overview of the project structure. 

{context_tree}
"""

ROLE_PROMPT_TEMPLATE = """
Active Role: {role_name}
{role_prompt}
"""

def format_system_prompt(
    project_context: str = "",
    model_name: str = "",
    context_window: int = 0,
    role_name: str = "",
    role_prompt: str = "",
) -> str:
    """
    Constructs the full system prompt, optionally including project context.
    
    Args:
        project_context: The string representation of the project structure/symbols.
                         If empty, the context section is omitted.
        model_name: The name of the current model.
        context_window: The context window size in tokens.
    """
    prompt = BASE_PROMPT
    
    # Add model context if available
    if model_name or context_window:
        prompt += MODEL_CONTEXT_PROMPT.format(
            model_name=model_name or "Unknown",
            context_window=context_window or "Unknown"
        )

    if role_name or role_prompt:
        prompt += ROLE_PROMPT_TEMPLATE.format(
            role_name=role_name or "default",
            role_prompt=role_prompt or "Follow the general Pico operating instructions.",
        )
    
    prompt += CONTEXT_PROMPT_TEMPLATE.format(context_tree=project_context)
        
    return prompt

def get_system_message(
    project_context: str = "",
    model_name: str = "",
    context_window: int = 0,
    role_name: str = "",
    role_prompt: str = "",
) -> Dict[str, str]:
    """
    Returns the system message dictionary formatted for the LLM API.
    """
    return {
        "role": "system",
        "content": format_system_prompt(
            project_context, model_name, context_window, role_name, role_prompt
        )
    }
