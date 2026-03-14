import shlex
import asyncio
from typing import List, Tuple, Optional, Union
from pico_chat.harness.commands.router import router

class PipelineParser:
    """
    Parses a shell-like command string into a chain of commands.
    Handles: | (pipe), && (and), || (or), ; (sequence)
    """
    
    @staticmethod
    def parse(cmd_string: str) -> List[List[Union[str, List[str]]]]:
        """
        Splits a command string into stages/groups.
        Example: "cat log.txt | grep ERROR && echo SUCCESS"
        Returns a priority-list for the engine.
        """
        # Complex parsing for pipes and operators
        # For Phase 1.2, we'll start with a basic version
        # to correctly split and identify operators.
        pass

async def execute_chain(cmd_string: str, initial_stdin: Optional[str] = None) -> Tuple[str, str, int, float]:
    """
    Core executor that parses the string and chains commands.
    Implements Layer 1: Lossless data flow.
    """
    # Simple shlex split can't handle complex ops directly,
    # but we can manually split on the main shell operators.
    
    # Placeholder implementation:
    # 1. Split on ; or && or || (not yet)
    # 2. Split on |
    
    stages = [s.strip() for s in cmd_string.split('|')]
    
    current_stdin = initial_stdin
    final_stdout = ""
    final_stderr = ""
    last_exit_code = 0
    total_duration = 0
    
    for i, stage in enumerate(stages):
        try:
            parts = shlex.split(stage)
            if not parts:
                continue
                
            cmd_name = parts[0]
            cmd_args = parts[1:]
            
            stdout, stderr, exit_code, duration = await router.run_single(cmd_name, cmd_args, current_stdin)
            
            total_duration += duration
            last_exit_code = exit_code
            
            if exit_code != 0:
                # If a command in a pipe fails, we usually stop and report the error
                # but different shells have different behaviors.
                # In Layer 1, we want to let the LLM see the error.
                return stdout, stderr, exit_code, total_duration
            
            # Chain stdout to stdin for next command
            current_stdin = stdout
            final_stdout = stdout
            final_stderr += stderr
            
        except Exception as e:
            return "", f"parser error in stage '{stage}': {str(e)}", 1, total_duration
            
    return final_stdout, final_stderr, last_exit_code, total_duration
