from typing import Any, Dict
from pico_chat.harness.commands.chain import execute_chain
from pico_chat.harness.commands.presentation import format_result

class RunTool:
    """
    Unified run(command, stdin) tool according to Phase 4.1.
    """
    def __init__(self, harness=None):
        self.harness = harness # Optional back-reference if needed

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "run",
                "description": "Execute shell-like commands and pipelines. Supports | (pipe), && (and), || (or), ; (sequence). Run 'help' to see available commands.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command line or pipeline to execute (e.g., 'cat log.txt | grep ERROR')."
                        },
                        "stdin": {
                            "type": "string",
                            "description": "Optional standard input to provide to the command (useful for writing files)."
                        }
                    },
                    "required": ["command"]
                }
            }
        }

    async def execute(self, command: str, stdin: str = None) -> str:
        """
        Executes the command chain and applies Layer 2 presentation formatting.
        """
        # Layer 1: Lossless Execution
        stdout, stderr, exit_code, duration_ms = await execute_chain(command, stdin)
        
        # Layer 2: Presentation Logic (Truncation, Metadata, Binary Guard)
        return format_result(stdout, stderr, exit_code, duration_ms)
