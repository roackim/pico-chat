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
    Supports: | (pipe), && (and), || (or), ; (sequence), > (redirect)
    """
    import re
    
    # Handle output redirection (>) - but only if it's NOT inside quotes
    output_file = None
    redirect_match = None
    
    # Find the LAST unquoted > in the command
    # This regex finds > that's not inside single or double quotes
    in_single = False
    in_double = False
    escape = False
    
    for i, char in enumerate(cmd_string):
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == '>' and not in_single and not in_double:
            # Found an unquoted >
            # Check if it's a shell redirection (preceded by whitespace or start of string)
            if i == 0 or cmd_string[i-1].isspace():
                redirect_match = i
    
    if redirect_match is not None:
        output_file = cmd_string[redirect_match + 1:].strip()
        cmd_string = cmd_string[:redirect_match].strip()
    
    # Parse chain operators (priority: ; lowest, then || and &&, then | highest)
    # Split by ; first (sequence - always execute)
    sequences = [s.strip() for s in cmd_string.split(';')]
    
    final_stdout = ""
    final_stderr = ""
    last_exit_code = 0
    total_duration = 0
    
    for seq in sequences:
        if not seq:
            continue
            
        # Split by || (or - execute next if previous failed)
        or_groups = [s.strip() for s in seq.split('||')]
        
        for or_group in or_groups:
            # Split by && (and - execute next only if previous succeeded)
            and_groups = [s.strip() for s in or_group.split('&&')]
            
            for and_group in and_groups:
                # Split by | (pipe - pass stdout to next stdin)
                stages = [s.strip() for s in and_group.split('|')]
                
                current_stdin = initial_stdin
                pipe_stdout = ""
                pipe_stderr = ""
                pipe_exit = 0
                
                for stage in stages:
                    try:
                        parts = shlex.split(stage)
                        if not parts:
                            continue
                            
                        cmd_name = parts[0]
                        cmd_args = parts[1:]
                        
                        stdout, stderr, exit_code, duration = await router.run_single(cmd_name, cmd_args, current_stdin)
                        
                        total_duration += duration
                        pipe_exit = exit_code
                        pipe_stderr += stderr
                        
                        if exit_code != 0:
                            # Pipe failed
                            pipe_stdout = stdout
                            break
                        
                        # Chain stdout to stdin for next command in pipe
                        current_stdin = stdout
                        pipe_stdout = stdout
                        
                    except Exception as e:
                        pipe_stdout = ""
                        pipe_stderr = f"parser error in stage '{stage}': {str(e)}"
                        pipe_exit = 1
                        break
                
                # Store results from this && group
                final_stdout = pipe_stdout
                final_stderr = pipe_stderr
                last_exit_code = pipe_exit
                
                # && logic: stop if command failed
                if pipe_exit != 0:
                    break
            
            # || logic: continue to next or_group only if this one failed
            if last_exit_code == 0:
                break
    
    # Handle output redirection if specified
    if output_file:
        try:
            import os
            dir_path = os.path.dirname(os.path.abspath(output_file))
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_stdout)
            
            # Return success message instead of the content
            final_stdout = f"Output written to {output_file}"
        except Exception as e:
            return "", f"redirection error: {str(e)}", 1, total_duration
            
    return final_stdout, final_stderr, last_exit_code, total_duration
