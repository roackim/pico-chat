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

Memory Management:
- Store important observations, decisions, file locations, and patterns in memory using the memorize tool.
- Update or correct existing memory entries when you discover new information.
- Memory persists across the conversation and survives edits/retries.
- Be aware that memory may become outdated; verify important details when necessary.
- Use memory to maintain context across long conversations and complex tasks.
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
