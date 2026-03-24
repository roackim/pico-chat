"""
Token estimation utilities.

Provides fast, pessimistic token count estimates for context management.
Uses character-based heuristics rather than actual tokenization for speed.
"""

def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a string.
    
    Uses pessimistic ratio of 1 token per 3 characters (overestimate).
    Actual tokenization varies by model, but this gives a safe upper bound.
    
    Args:
        text: Input text
        
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return len(text) // 3 + 1  # Pessimistic, rounds up


def estimate_message_tokens(message: dict) -> int:
    """
    Estimate tokens for a single message dict.
    
    Args:
        message: Message dict with 'role', 'content', optional 'tool_calls', etc.
        
    Returns:
        Estimated token count including overhead
    """
    total = 4  # Message formatting overhead
    
    # Content
    content = message.get("content")
    if content:
        total += estimate_tokens(content)
    
    # Tool calls
    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            # Function name + arguments
            total += estimate_tokens(tc.get("function", {}).get("name", ""))
            total += estimate_tokens(tc.get("function", {}).get("arguments", ""))
    
    # Tool call ID
    if message.get("tool_call_id"):
        total += 10  # Overhead for tool response
    
    return total


def estimate_messages_tokens(messages: list) -> int:
    """
    Estimate total tokens for a list of messages.
    
    Args:
        messages: List of message dicts
        
    Returns:
        Total estimated token count
    """
    return sum(estimate_message_tokens(msg) for msg in messages)
