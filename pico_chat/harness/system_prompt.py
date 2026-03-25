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

Memory Usage:
- Use 'memorize' as a scratchpad for the current conversation session.
- Store important observations, TODOs, decisions, and facts to keep them near the system prompt.
- Only memorize concrete information - never store placeholders like "unknown".
- After calling memory tools, ALWAYS provide a text response to the user - never end with just tool calls.
- Examples: active tasks, user preferences given in this session, project goals, key decisions.
- Use 'forget' to clean up completed tasks or outdated information.
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

def format_system_prompt(project_context: str = "", model_name: str = "", context_window: int = 0) -> str:
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
    
    prompt += CONTEXT_PROMPT_TEMPLATE.format(context_tree=project_context)
        
    return prompt

def get_system_message(project_context: str = "", model_name: str = "", context_window: int = 0) -> Dict[str, str]:
    """
    Returns the system message dictionary formatted for the LLM API.
    """
    return {
        "role": "system",
        "content": format_system_prompt(project_context, model_name, context_window)
    }
