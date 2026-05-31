"""
Test suite for web search functionality.

Tests SearchTools for DuckDuckGo and Wikipedia search,
permission enforcement, and rate limiting for subagents.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pico_chat.harness.tools import SearchTools, ToolError
from pico_chat.harness.tool_wrappers import SearchWebTool, SearchWikiTool
from pico_chat.harness.tool_permissions import (
    ToolPermissionsProfile,
    FilePermissions,
    RunPermissions,
)


class TestSearchToolsBasic:
    """Test basic SearchTools functionality."""
    
    def test_search_web_basic_query(self):
        """Test basic DuckDuckGo search query."""
        tools = SearchTools()
        
        # Mock httpx response
        mock_html = '''
        <div class="result">
            <a class="result__a" href="https://example.com/python">Python Tutorial</a>
            <a class="result__snippet">Learn Python programming from scratch</a>
        </div>
        '''
        
        with patch('httpx.get') as mock_get:
            mock_response = Mock()
            mock_response.text = mock_html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            result = tools.search_web("python tutorial", max_results=3)
            
            assert "DuckDuckGo search results" in result
            assert "python tutorial" in result
            assert "Python Tutorial" in result
            assert "https://example.com/python" in result
    
    def test_search_web_with_time_range(self):
        """Test DuckDuckGo search with time range filter."""
        tools = SearchTools()
        
        with patch('httpx.get') as mock_get:
            mock_response = Mock()
            mock_response.text = '<html></html>'
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            tools.search_web("python news", max_results=3, time_range="week")
            
            # Verify time filter was passed
            call_args = mock_get.call_args
            assert call_args[1]['params']['df'] == 'w'
    
    def test_search_web_no_results(self):
        """Test DuckDuckGo search with no results."""
        tools = SearchTools()
        
        with patch('httpx.get') as mock_get:
            mock_response = Mock()
            mock_response.text = '<html><body>No results</body></html>'
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            result = tools.search_web("xyzabc123nonexistent", max_results=3)
            
            assert "No results found" in result or "No valid results" in result
            assert "search_web" in result
    
    def test_search_web_timeout(self):
        """Test DuckDuckGo search timeout handling."""
        tools = SearchTools()
        
        with patch('httpx.get') as mock_get:
            import httpx
            mock_get.side_effect = httpx.TimeoutException("Timeout")
            
            with pytest.raises(ToolError, match="timed out"):
                tools.search_web("test query")
    
    def test_search_web_http_error(self):
        """Test DuckDuckGo search HTTP error handling."""
        tools = SearchTools()
        
        with patch('httpx.get') as mock_get:
            import httpx
            mock_get.side_effect = httpx.HTTPError("Connection failed")
            
            with pytest.raises(ToolError, match="request failed"):
                tools.search_web("test query")
    
    def test_search_wiki_basic_query(self):
        """Test basic Wikipedia search query."""
        tools = SearchTools()
        
        # Mock Wikipedia API response
        mock_json = {
            'query': {
                'search': [
                    {
                        'title': 'Python (programming language)',
                        'snippet': 'Python is a high-level programming language'
                    }
                ]
            }
        }
        
        with patch('httpx.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_json
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            result = tools.search_wiki("Python programming language", max_results=3)
            
            assert "Wikipedia search results" in result
            assert "Python (programming language)" in result
            assert "https://en.wikipedia.org/wiki/" in result
            assert "high-level programming language" in result
    
    def test_search_wiki_no_results(self):
        """Test Wikipedia search with no results."""
        tools = SearchTools()
        
        mock_json = {'query': {'search': []}}
        
        with patch('httpx.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_json
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            result = tools.search_wiki("xyzabc123nonexistent", max_results=3)
            
            assert "No" in result and "found" in result
            assert "search_wiki" in result
    
    def test_search_wiki_timeout(self):
        """Test Wikipedia search timeout handling."""
        tools = SearchTools()
        
        with patch('httpx.get') as mock_get:
            import httpx
            mock_get.side_effect = httpx.TimeoutException("Timeout")
            
            with pytest.raises(ToolError, match="timed out"):
                tools.search_wiki("test query")
    
    def test_search_wiki_max_results(self):
        """Test Wikipedia search respects max_results."""
        tools = SearchTools()
        
        mock_json = {
            'query': {
                'search': [
                    {'title': f'Result {i}', 'snippet': f'Snippet {i}'}
                    for i in range(10)
                ]
            }
        }
        
        with patch('httpx.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_json
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            result = tools.search_wiki("test", max_results=3)
            
            # Should only have 3 results
            assert result.count('[1]') == 1
            assert result.count('[2]') == 1
            assert result.count('[3]') == 1
            assert '[4]' not in result


class TestSearchToolWrappers:
    """Test SearchToolWrapper functionality and rate limiting."""
    
    def test_search_web_wrapper_basic(self):
        """Test SearchWebTool wrapper basic execution."""
        search_tools = SearchTools()
        
        with patch.object(search_tools, 'search_web', return_value="Mock results"):
            wrapper = SearchWebTool(search_tools, max_results=3, search_limit=None)
            result = wrapper.execute(query="python")
            
            assert result == "Mock results"
            search_tools.search_web.assert_called_once_with("python", max_results=3, time_range=None)
    
    def test_search_web_wrapper_with_time_range(self):
        """Test SearchWebTool wrapper with time_range parameter."""
        search_tools = SearchTools()
        
        with patch.object(search_tools, 'search_web', return_value="Mock results"):
            wrapper = SearchWebTool(search_tools, max_results=3, search_limit=None)
            result = wrapper.execute(query="python", time_range="week")
            
            search_tools.search_web.assert_called_once_with("python", max_results=3, time_range="week")
    
    def test_search_web_rate_limit_main_agent(self):
        """Test that main agent (depth=0) has no rate limit."""
        search_tools = SearchTools()
        
        with patch.object(search_tools, 'search_web', return_value="Mock results"):
            # Main agent: search_limit=None
            wrapper = SearchWebTool(search_tools, max_results=3, search_limit=None)
            
            # Should allow unlimited searches
            for i in range(10):
                result = wrapper.execute(query=f"query {i}")
                assert result == "Mock results"
            
            assert search_tools.search_web.call_count == 10
    
    def test_search_web_rate_limit_subagent(self):
        """Test that subagent (depth>0) has rate limit."""
        search_tools = SearchTools()
        
        with patch.object(search_tools, 'search_web', return_value="Mock results"):
            # Subagent: search_limit=3
            wrapper = SearchWebTool(search_tools, max_results=10, search_limit=3)
            
            # First 3 searches should work
            for i in range(3):
                result = wrapper.execute(query=f"query {i}")
                assert result == "Mock results"
            
            # 4th search should be rate limited
            result = wrapper.execute(query="query 4")
            assert "Rate limit reached" in result
            
            # Verify only 3 actual searches were made
            assert search_tools.search_web.call_count == 3
    
    def test_search_wiki_wrapper_basic(self):
        """Test SearchWikiTool wrapper basic execution."""
        search_tools = SearchTools()
        
        with patch.object(search_tools, 'search_wiki', return_value="Mock wiki results"):
            wrapper = SearchWikiTool(search_tools, max_results=3, search_limit=None)
            result = wrapper.execute(query="Python")
            
            assert result == "Mock wiki results"
            search_tools.search_wiki.assert_called_once_with("Python", max_results=3)
    
    def test_search_wiki_rate_limit_subagent(self):
        """Test that subagent wiki search has rate limit."""
        search_tools = SearchTools()
        
        with patch.object(search_tools, 'search_wiki', return_value="Mock results"):
            # Subagent: search_limit=3
            wrapper = SearchWikiTool(search_tools, max_results=10, search_limit=3)
            
            # First 3 searches should work
            for i in range(3):
                result = wrapper.execute(query=f"query {i}")
                assert result == "Mock results"
            
            # 4th search should be rate limited
            result = wrapper.execute(query="query 4")
            assert "Rate limit reached" in result
            
            # Verify only 3 actual searches were made
            assert search_tools.search_wiki.call_count == 3
    
    def test_search_wrapper_error_handling(self):
        """Test that wrappers handle ToolError gracefully."""
        search_tools = SearchTools()
        
        with patch.object(search_tools, 'search_web', side_effect=ToolError("Network error")):
            wrapper = SearchWebTool(search_tools, max_results=3, search_limit=None)
            result = wrapper.execute(query="test")
            
            assert "[search_web]" in result
            assert "Network error" in result


class TestSearchPermissions:
    """Test search permission enforcement."""
    
    def test_search_allowed_in_permissive_profile(self):
        """Test that search is allowed in permissive profile."""
        from pico_chat.harness.tool_permissions import permissive
        
        assert permissive.get_search_permission() == "allow"
    
    def test_search_denied_in_locked_profile(self):
        """Test that search is denied in locked profile."""
        from pico_chat.harness.tool_permissions import locked
        
        assert locked.get_search_permission() == "deny"
    
    def test_search_allowed_in_scaffolder_profile(self):
        """Test that search is allowed in scaffolder (subagent) profile."""
        from pico_chat.harness.tool_permissions import scaffolder
        
        # Subagents can search for library docs
        assert scaffolder.get_search_permission() == "allow"
    
    def test_search_ask_in_strict_profile(self):
        """Test that search requires confirmation in strict profile."""
        from pico_chat.harness.tool_permissions import strict
        
        assert strict.get_search_permission() == "ask"
    
    def test_custom_profile_with_search(self):
        """Test creating custom profile with search permissions."""
        custom = ToolPermissionsProfile(
            name="custom",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
            search="ask",
        )
        
        assert custom.get_search_permission() == "ask"


class TestSearchIntegration:
    """Test search integration with the tool system."""
    
    def test_search_tools_in_create_minimal_tools(self, tmp_path):
        """Test that search tools are included in minimal toolset."""
        from pico_chat.harness.tool_wrappers import create_minimal_tools
        
        # Main agent (depth=0)
        tools = create_minimal_tools(workspace_path=tmp_path, depth=0)
        
        assert "search_web" in tools
        assert "search_wiki" in tools
        assert isinstance(tools["search_web"], SearchWebTool)
        assert isinstance(tools["search_wiki"], SearchWikiTool)
    
    def test_search_tools_main_agent_config(self, tmp_path):
        """Test that main agent gets correct search configuration."""
        from pico_chat.harness.tool_wrappers import create_minimal_tools
        
        # Main agent (depth=0)
        tools = create_minimal_tools(workspace_path=tmp_path, depth=0)
        
        search_web = tools["search_web"]
        search_wiki = tools["search_wiki"]
        
        # Main agent: max_results=3, no rate limit
        assert search_web.max_results == 3
        assert search_web.search_limit is None
        assert search_wiki.max_results == 3
        assert search_wiki.search_limit is None
    
    def test_search_tools_subagent_config(self, tmp_path):
        """Test that subagent gets correct search configuration."""
        from pico_chat.harness.tool_wrappers import create_minimal_tools
        
        # Subagent (depth=1)
        tools = create_minimal_tools(workspace_path=tmp_path, depth=1)
        
        search_web = tools["search_web"]
        search_wiki = tools["search_wiki"]
        
        # Subagent: max_results=10, rate limit=3
        assert search_web.max_results == 10
        assert search_web.search_limit == 3
        assert search_wiki.max_results == 10
        assert search_wiki.search_limit == 3
    
    def test_search_tool_schema_generation(self, tmp_path):
        """Test that search tools generate proper OpenAI schemas."""
        from pico_chat.harness.tool_wrappers import create_minimal_tools
        
        tools = create_minimal_tools(workspace_path=tmp_path, depth=0)
        
        web_schema = tools["search_web"].get_schema()
        wiki_schema = tools["search_wiki"].get_schema()
        
        # Check web search schema
        assert web_schema["type"] == "function"
        assert web_schema["function"]["name"] == "search_web"
        assert "query" in web_schema["function"]["parameters"]["properties"]
        assert "time_range" in web_schema["function"]["parameters"]["properties"]
        
        # Check Wiki schema
        assert wiki_schema["type"] == "function"
        assert wiki_schema["function"]["name"] == "search_wiki"
        assert "query" in wiki_schema["function"]["parameters"]["properties"]
