"""
Token estimation utilities.

Provides fast, pessimistic token count estimates for context management.
Uses character-based heuristics rather than actual tokenization for speed.
Interpolates between language and code ratios based on symbol density.
"""

# Token estimation constants
CHARS_PER_TOKEN_LANGUAGE = 4.0  # Natural language compresses well
CHARS_PER_TOKEN_CODE = 2.5      # Code with symbols is denser
CODE_SYMBOLS = frozenset("{}[]()<>.,;:=+-*/%&|!~^`@#$\\\"'")


def _calculate_code_ratio(text: str) -> float:
    """
    Calculate the proportion of code-like content based on symbol density.
    
    Args:
        text: Input text
        
    Returns:
        Ratio from 0.0 (pure language) to 1.0 (pure code)
    """
    if not text:
        return 0.0
    
    symbol_count = sum(1 for c in text if c in CODE_SYMBOLS)
    symbol_density = symbol_count / len(text)
    
    # Map density to code ratio
    # Low density (< 5%) = language, high density (> 20%) = code
    if symbol_density < 0.05:
        return 0.0
    elif symbol_density > 0.20:
        return 1.0
    else:
        # Linear interpolation between 5% and 20%
        return (symbol_density - 0.05) / 0.15


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a string.
    
    Interpolates between language and code token ratios based on symbol density.
    This provides better estimates than a fixed constant while staying fast.
    
    Args:
        text: Input text
        
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    
    code_ratio = _calculate_code_ratio(text)
    
    # Interpolate chars per token based on content type
    chars_per_token = (
        CHARS_PER_TOKEN_LANGUAGE * (1 - code_ratio) +
        CHARS_PER_TOKEN_CODE * code_ratio
    )
    
    return int(len(text) / chars_per_token) + 1  # Add 1 for safety


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
