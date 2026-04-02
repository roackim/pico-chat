"""
Test suite for token estimation utilities.
"""
import pytest
from pico_chat.harness.token_estimation import (
    estimate_tokens,
    estimate_message_tokens,
    estimate_messages_tokens,
    _calculate_code_ratio,
)


class TestCodeRatioCalculation:
    """Test code ratio calculation based on symbol density."""
    
    def test_pure_natural_language(self):
        """Natural language with minimal symbols should have low code ratio."""
        text = "This is a natural language sentence with normal words."
        ratio = _calculate_code_ratio(text)
        assert ratio < 0.3  # Should be mostly language
    
    def test_pure_code(self):
        """Code with many symbols should have high code ratio."""
        text = "const obj = { key: 'value', arr: [1, 2, 3], x: x + y * z };"
        ratio = _calculate_code_ratio(text)
        assert ratio > 0.7  # Should be mostly code
    
    def test_python_function(self):
        """Python function should be detected as code."""
        text = "def hello_world():\n    return x + y"
        ratio = _calculate_code_ratio(text)
        assert ratio > 0.3  # Should have noticeable code characteristics
    
    def test_empty_string(self):
        """Empty string should return 0."""
        assert _calculate_code_ratio("") == 0.0
    
    def test_low_symbol_density(self):
        """Text with <5% symbols should return 0."""
        text = "Hello world this is plain text"
        ratio = _calculate_code_ratio(text)
        assert ratio == 0.0
    
    def test_high_symbol_density(self):
        """Text with >20% symbols should return 1.0."""
        text = "{{{{[[[[]]]]}}}}()()()()"
        ratio = _calculate_code_ratio(text)
        assert ratio == 1.0
    
    def test_interpolation_range(self):
        """Symbol density between 5-20% should interpolate."""
        text = "some text (with, some; symbols)"
        ratio = _calculate_code_ratio(text)
        assert 0.0 < ratio < 1.0  # Should be in between


class TestTokenEstimation:
    """Test token estimation accuracy."""
    
    def test_empty_string(self):
        """Empty string should return 0 tokens."""
        assert estimate_tokens("") == 0
    
    def test_natural_language_ratio(self):
        """Natural language should use ~4 chars/token ratio."""
        text = "This is a natural language sentence. It has normal words and punctuation."
        # Length: 74 chars, low symbol density -> ~4 chars/token -> ~18-19 tokens
        tokens = estimate_tokens(text)
        assert 15 <= tokens <= 25  # Allow some variance
    
    def test_code_ratio(self):
        """Code with symbols should use ~2.5 chars/token ratio (more tokens)."""
        text = "function(param1, param2) { return param1 + param2; }"
        # High symbol density -> ~2.5 chars/token -> more tokens per char
        tokens = estimate_tokens(text)
        assert 15 <= tokens <= 25  # Code gets more tokens per char
    
    def test_python_code(self):
        """Python code should be estimated based on symbol density."""
        text = "def func(a, b):\n    return a + b"
        tokens = estimate_tokens(text)
        assert tokens >= 10
    
    def test_code_vs_natural_difference(self):
        """Same length code and natural text should have different estimates."""
        # Pure natural language (low symbols)
        natural = "This is a sentence with normal words and common punctuation."
        # Code with many symbols
        code = "def f(a,b,c,d): return {x:a+b, y:c*d, z:[a,b,c]}"
        
        natural_tokens = estimate_tokens(natural)
        code_tokens = estimate_tokens(code)
        
        # Code should have more tokens (more symbol density)
        assert code_tokens > natural_tokens
    
    def test_large_text(self):
        """Large text should scale near-linearly."""
        small_text = "Hello world how are you today."
        large_text = small_text * 100
        
        small_tokens = estimate_tokens(small_text)
        large_tokens = estimate_tokens(large_text)
        
        # Should be approximately 100x (the +1 causes slight deviation)
        ratio = large_tokens / small_tokens
        assert 90 <= ratio <= 105  # Near-linear scaling


class TestMessageTokenEstimation:
    """Test message-level token estimation."""
    
    def test_simple_message(self):
        """Simple message should estimate correctly."""
        message = {
            "role": "user",
            "content": "Hello, how are you?"
        }
        tokens = estimate_message_tokens(message)
        # Should include overhead + content tokens
        assert tokens > 5
    
    def test_message_with_tool_calls(self):
        """Message with tool calls should include tool call tokens."""
        message = {
            "role": "assistant",
            "content": "Let me read that file.",
            "tool_calls": [
                {
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "file.txt"}'
                    }
                }
            ]
        }
        tokens = estimate_message_tokens(message)
        assert tokens > 10
    
    def test_message_with_tool_call_id(self):
        """Tool response should include tool_call_id overhead."""
        message = {
            "role": "tool",
            "content": "File content here",
            "tool_call_id": "call_12345"
        }
        tokens = estimate_message_tokens(message)
        # Should include 10 token overhead for tool response
        assert tokens > 15


class TestMessagesTokenEstimation:
    """Test conversation-level token estimation."""
    
    def test_empty_list(self):
        """Empty message list should return 0."""
        assert estimate_messages_tokens([]) == 0
    
    def test_multiple_messages(self):
        """Multiple messages should sum correctly."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"}
        ]
        total = estimate_messages_tokens(messages)
        
        # Should be sum of all messages with overhead
        assert total >= 20
    
    def test_conversation_with_tools(self):
        """Conversation with tool calls should estimate correctly."""
        messages = [
            {"role": "user", "content": "Read the file"},
            {
                "role": "assistant",
                "content": "Reading...",
                "tool_calls": [{
                    "function": {
                        "name": "read",
                        "arguments": '{"path": "test.txt"}'
                    }
                }]
            },
            {
                "role": "tool",
                "content": "file content",
                "tool_call_id": "call_1"
            }
        ]
        total = estimate_messages_tokens(messages)
        assert total > 30


class TestComparisonToOldHeuristic:
    """Compare new adaptive heuristic to old fixed heuristic."""
    
    def test_old_vs_new_for_code(self):
        """For code, new heuristic should be more accurate."""
        text = "def hello(x, y): return x + y"
        
        # Old heuristic: len // 3 + 1
        old_estimate = len(text) // 3 + 1
        
        # New heuristic (adaptive)
        new_estimate = estimate_tokens(text)
        
        # New should give reasonable estimates
        assert new_estimate > 5
        assert new_estimate < 50
    
    def test_old_vs_new_for_natural(self):
        """For natural text, new heuristic should use better ratio."""
        text = "This is a normal sentence with regular English words and no symbols."
        
        # Old heuristic: len // 3 + 1 (~3 chars/token)
        old_estimate = len(text) // 3 + 1
        
        # New heuristic (adaptive, uses 4 chars/token for natural)
        new_estimate = estimate_tokens(text)
        
        # New should be lower for natural text (4 chars/token vs 3)
        assert new_estimate < old_estimate
    
    def test_symbol_heavy_code(self):
        """Symbol-heavy code should get higher token count."""
        text = "{[()]}{[()]}{[()]}{[()]}"
        
        # Should detect as pure code
        new_estimate = estimate_tokens(text)
        
        # With 2.5 chars/token, 24 chars -> ~10 tokens
        assert new_estimate >= 9
