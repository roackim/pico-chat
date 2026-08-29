from typing import List, Dict

# Base system prompt template
BASE_PROMPT = """
Identity: Pico, coding AI agent.

Instructions:
- Provide concise, professional, and technical answers.
- Prioritize technical accuracy and completeness over brevity.
- No emojis, metaphors, or conversational filler.
- Answer directly when the request is simple or you already have enough context.
- For simple fixes, make one decisive edit rather than a chain of exploratory steps.
- Ask the user for information they may have, especially for opinionated choices (e.g. tech stack, design direction); otherwise state your assumption and proceed.
- Break genuinely complex tasks into a short sequence of steps; keep it minimal.
- Use tool only when necessary; prefer reasoning and code generation over tool calls.
- Follow existing codebase styles and best practices.
- State clearly if you are uncertain or missing information.
- At the end of a task, do a proper check to assess whether the change actually succeeded.
- If a tool call fails or a patch doesn't apply cleanly, surface the failure rather than silently retrying.
- While investigating, resurface important findings to the user — especially if they imply a change of direction — rather than going deep in the wrong direction autonomously.
- Don't expand scope beyond what was asked; if you discover related issues, mention them rather than fixing them unprompted.
- When instructions conflict, prefer surfacing to the user over autonomous action.
- Confirm with the user before attempting or executing dangerous or irreversible operations.
- You are done when you have a correct, complete answer or a working change; hand back control then.
- Never expose secrets or credentials in output.
"""

# MODEL_CONTEXT_PROMPT = """
# Model Context:
# Model used: {model_name}
# Context window: {context_window} max tokens
# """


import datetime
import platform
import os
import shutil
                                                                                      
def get_context_string() -> str:
    now = datetime.datetime.now()
    tz = now.astimezone().tzname()
    os_info = f"{platform.system()} {platform.release()}"
    shell = os.environ.get("SHELL") or shutil.which("bash") or "unknown"
    return (
        ""
        f"Date: {now.strftime('%Y-%m-%d')}\n"
        f"Time: {now.strftime('%H:%M:%S')} {tz}\n"
        f"OS: {os_info}\n"
        f"Shell: {os.path.basename(shell)}"
    )

# NOTE: disabled project's context tree because it can be very long and is not very usefull
# CONTEXT_PROMPT_TEMPLATE = """
# Project Context:
# The following is an overview of the project structure.
# {context_tree}
# """

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
    # if model_name or context_window:
        # prompt += MODEL_CONTEXT_PROMPT.format(
            # model_name=model_name or "Unknown",
            # context_window=context_window or "Unknown"
        # )

    if role_name or role_prompt:
        prompt += ROLE_PROMPT_TEMPLATE.format(
            role_name=role_name or "default",
            role_prompt=role_prompt or "Follow the general Pico operating instructions.",
        )
    
    # disabled project's context tree
    # prompt += CONTEXT_PROMPT_TEMPLATE.format(context_tree=project_context)
    
    prompt += get_context_string()
        
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
