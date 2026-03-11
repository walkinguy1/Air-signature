"""
GestureGuard - Action Execution Module
Handles executing profile actions (launch apps, hotkeys, scripts, etc.)
FR-4: Action Execution Engine
"""

import os
import sys
import subprocess
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import platform

# Platform-specific imports
if platform.system() == "Windows":
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
else:
    # For non-Windows, we'll use alternative approaches
    pyautogui = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GestureGuard.Actions")


class ActionResult:
    """Result of action execution"""
    
    def __init__(self, success: bool, message: str, action_type: str = ""):
        self.success = success
        self.message = message
        self.action_type = action_type
        self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    def __repr__(self):
        status = "SUCCESS" if self.success else "FAILED"
        return f"[{status}] {self.action_type}: {self.message}"


class ActionExecutor:
    """
    Executes profile actions: launch, close_app, hotkey, script, switch_desktop
    FR-4.1: Support action types: launch, close_app, hotkey, script, switch_desktop
    """
    
    def __init__(self, action_delay: float = 0.5):
        """
        Initialize action executor.
        
        Args:
            action_delay: Delay between sequential actions (seconds)
        """
        self.action_delay = action_delay
        self.action_results: List[ActionResult] = []
        
        # Initialize platform-specific components
        self._init_platform()
    
    def _init_platform(self) -> None:
        """Initialize platform-specific components"""
        self.platform = platform.system()
        logger.info(f"Running on platform: {self.platform}")
        
        if self.platform == "Windows":
            # Test pyautogui availability
            try:
                screen_size = pyautogui.size()
                logger.info(f"Screen size: {screen_size}")
            except Exception as e:
                logger.warning(f"pyautogui not available: {e}")
                import core.actions
                core.actions.pyautogui = None
    
    def execute_action(self, action: Dict[str, Any]) -> ActionResult:
        """
        Execute a single action.
        
        Args:
            action: Action dictionary with type and parameters
            
        Returns:
            ActionResult indicating success/failure
        """
        action_type = action.get("type", "")
        
        try:
            if action_type == "launch":
                return self._execute_launch(action)
            elif action_type == "close_app":
                return self._execute_close_app(action)
            elif action_type == "hotkey":
                return self._execute_hotkey(action)
            elif action_type == "script":
                return self._execute_script(action)
            elif action_type == "switch_desktop":
                return self._execute_switch_desktop(action)
            else:
                return ActionResult(False, f"Unknown action type: {action_type}", action_type)
                
        except Exception as e:
            logger.error(f"Action execution error: {e}")
            return ActionResult(False, str(e), action_type)
    
    def execute_actions(self, actions: List[Dict[str, Any]]) -> List[ActionResult]:
        """
        Execute a sequence of actions.
        FR-4.2: Actions SHALL execute sequentially with configurable delays
        
        Args:
            actions: List of action dictionaries
            
        Returns:
            List of ActionResults
        """
        self.action_results = []
        results = []
        
        for i, action in enumerate(actions):
            logger.info(f"Executing action {i+1}/{len(actions)}: {action}")
            
            result = self.execute_action(action)
            results.append(result)
            
            # Log result
            logger.info(f"Result: {result}")
            
            # FR-4.4: Failed actions should NOT block subsequent actions
            if not result.success:
                logger.warning(f"Action {i+1} failed but continuing...")
            
            # Delay between actions (except for last)
            if i < len(actions) - 1:
                delay = action.get("delay", self.action_delay)
                time.sleep(delay)
        
        self.action_results = results
        return results
    
    def _execute_launch(self, action: Dict[str, Any]) -> ActionResult:
        """
        Launch an application.
        
        Action format:
        {
            "type": "launch",
            "path": "path/to/app.exe",
            "args": ["arg1", "arg2"],  // optional
            "wait": 5                  // seconds to wait after launch
        }
        """
        app_path = action.get("path", "")
        args = action.get("args", [])
        wait_time = action.get("wait", 0)
        
        if not app_path:
            return ActionResult(False, "No path specified for launch", "launch")
        
        try:
            # Expand user path
            app_path = os.path.expanduser(app_path)
            
            # Check if executable exists (for local files)
            if os.path.exists(app_path):
                logger.info(f"Launching local app: {app_path}")
            
            # Build command
            cmd = [app_path] + args
            
            # Start process (don't wait)
            subprocess.Popen(cmd, detached=True)
            
            if wait_time > 0:
                time.sleep(wait_time)
            
            return ActionResult(True, f"Launched: {app_path}", "launch")
            
        except FileNotFoundError:
            return ActionResult(False, f"Executable not found: {app_path}", "launch")
        except Exception as e:
            return ActionResult(False, f"Launch failed: {str(e)}", "launch")
    
    def _execute_close_app(self, action: Dict[str, Any]) -> ActionResult:
        """
        Close an application.
        
        Action format:
        {
            "type": "close_app",
            "target": "chrome.exe"  // process name
        }
        """
        target = action.get("target", "")
        
        if not target:
            return ActionResult(False, "No target specified for close_app", "close_app")
        
        try:
            if self.platform == "Windows":
                # Use taskkill to terminate process
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", target],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    return ActionResult(True, f"Closed: {target}", "close_app")
                else:
                    return ActionResult(False, f"Process not found: {target}", "close_app")
            else:
                # Unix-like: use pkill
                result = subprocess.run(
                    ["pkill", "-f", target],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    return ActionResult(True, f"Closed: {target}", "close_app")
                else:
                    return ActionResult(False, f"Process not found: {target}", "close_app")
                    
        except Exception as e:
            return ActionResult(False, f"Close failed: {str(e)}", "close_app")
    
    def _execute_hotkey(self, action: Dict[str, Any]) -> ActionResult:
        """
        Execute a hotkey combination.
        
        Action format:
        {
            "type": "hotkey",
            "keys": ["win", "d"]  // Modifier + key
        }
        """
        keys = action.get("keys", [])
        
        if not keys:
            return ActionResult(False, "No keys specified for hotkey", "hotkey")
        
        if pyautogui is None:
            return ActionResult(False, "pyautogui not available on this platform", "hotkey")
        
        try:
            # Map common key names
            key_mapping = {
                "win": "win",
                "ctrl": "ctrl",
                "alt": "alt",
                "shift": "shift",
                "enter": "enter",
                "tab": "tab",
                "esc": "esc",
                "up": "up",
                "down": "down",
                "left": "left",
                "right": "right",
                "space": "space"
            }
            
            # Convert keys to pyautogui format
            hotkey_keys = [key_mapping.get(k.lower(), k) for k in keys]
            
            # Execute hotkey
            pyautogui.hotkey(*hotkey_keys)
            
            return ActionResult(True, f"Executed hotkey: {'+'.join(keys)}", "hotkey")
            
        except Exception as e:
            return ActionResult(False, f"Hotkey failed: {str(e)}", "hotkey")
    
    def _execute_script(self, action: Dict[str, Any]) -> ActionResult:
        """
        Run a custom script.
        
        Action format:
        {
            "type": "script",
            "path": "path/to/script.py",
            "args": ["arg1"],       // optional
            "wait": true            // wait for completion
        }
        """
        script_path = action.get("path", "")
        args = action.get("args", [])
        wait = action.get("wait", False)
        
        if not script_path:
            return ActionResult(False, "No path specified for script", "script")
        
        try:
            script_path = os.path.expanduser(script_path)
            
            if not os.path.exists(script_path):
                return ActionResult(False, f"Script not found: {script_path}", "script")
            
            # Determine interpreter
            ext = Path(script_path).suffix
            if ext == ".py":
                cmd = ["python", script_path] + args
            elif ext == ".sh":
                cmd = ["bash", script_path] + args
            elif ext == ".bat" or ext == ".cmd":
                cmd = [script_path] + args
            else:
                cmd = [script_path] + args
            
            # Execute
            if wait:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                success = result.returncode == 0
                message = f"Script completed with code {result.returncode}"
            else:
                subprocess.Popen(cmd, detached=True)
                success = True
                message = "Script started"
            
            return ActionResult(success, message, "script")
            
        except subprocess.TimeoutExpired:
            return ActionResult(False, "Script timed out", "script")
        except Exception as e:
            return ActionResult(False, f"Script error: {str(e)}", "script")
    
    def _execute_switch_desktop(self, action: Dict[str, Any]) -> ActionResult:
        """
        Switch to a virtual desktop.
        
        Action format:
        {
            "type": "switch_desktop",
            "desktop": 2  // Desktop number (1-based)
        }
        """
        desktop_num = action.get("desktop", 1)
        
        try:
            if self.platform == "Windows":
                # Windows 10/11: Use Ctrl+Win+Arrow keys
                if pyautogui is None:
                    return ActionResult(False, "pyautogui not available", "switch_desktop")
                
                # Note: This requires Virtual Desktop feature
                # Using PowerShell for more reliable desktop switching
                ps_script = f'''
                $ desktops = Get-Process -Name "explorer" -ErrorAction SilentlyContinue
                if ($desktops) {{
                    $shell = New-Object -ComObject Shell.Application
                    $shell.WindowSwitcher()
                }}
                '''
                
                # Simple approach: use Win+Tab to open view, then navigate
                # For now, just minimize all as fallback
                pyautogui.hotkey("win", "d")
                return ActionResult(True, f"Desktop switch requested (Win+D for now)", "switch_desktop")
                
            else:
                # Linux: Use wmctrl
                result = subprocess.run(
                    ["wmctrl", "-s", str(desktop_num - 1)],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    return ActionResult(True, f"Switched to desktop {desktop_num}", "switch_desktop")
                else:
                    return ActionResult(False, "wmctl not available", "switch_desktop")
                    
        except Exception as e:
            return ActionResult(False, f"Desktop switch failed: {str(e)}", "switch_desktop")
    
    def validate_action(self, action: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate an action before saving to profile.
        FR-3.3: Validate profile actions at creation time
        
        Args:
            action: Action to validate
            
        Returns:
            Tuple of (is_valid, message)
        """
        action_type = action.get("type", "")
        
        if action_type == "launch":
            path = action.get("path", "")
            if not path:
                return False, "Launch action requires 'path' field"
            
            # Check if local file exists
            expanded = os.path.expanduser(path)
            if not os.path.exists(expanded):
                # Could be a system command, try which
                if self.platform == "Windows":
                    where = subprocess.run(["where", path], capture_output=True)
                    if where.returncode != 0:
                        return False, f"Executable not found: {path}"
                else:
                    which = subprocess.run(["which", path], capture_output=True)
                    if which.returncode != 0:
                        return False, f"Executable not found: {path}"
            
            return True, "Valid"
        
        elif action_type == "close_app":
            target = action.get("target", "")
            if not target:
                return False, "close_app requires 'target' field"
            return True, "Valid"
        
        elif action_type == "hotkey":
            keys = action.get("keys", [])
            if not keys:
                return False, "hotkey requires 'keys' field"
            return True, "Valid"
        
        elif action_type == "script":
            path = action.get("path", "")
            if not path:
                return False, "script requires 'path' field"
            
            expanded = os.path.expanduser(path)
            if not os.path.exists(expanded):
                return False, f"Script not found: {path}"
            
            return True, "Valid"
        
        elif action_type == "switch_desktop":
            desktop = action.get("desktop", 1)
            if not isinstance(desktop, int) or desktop < 1:
                return False, "desktop must be positive integer"
            return True, "Valid"
        
        return False, f"Unknown action type: {action_type}"
    
    def get_action_results(self) -> List[ActionResult]:
        """Get results from last action execution"""
        return self.action_results


# Helper functions
def lock_workstation() -> ActionResult:
    """Lock the workstation (security feature)"""
    try:
        if platform.system() == "Windows":
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
            return ActionResult(True, "Workstation locked", "lock")
        else:
            # Unix-like: use loginctl
            subprocess.run(["loginctl", "lock-session"])
            return ActionResult(True, "Workstation locked", "lock")
    except Exception as e:
        return ActionResult(False, f"Lock failed: {str(e)}", "lock")


if __name__ == "__main__":
    # Test action executor
    print("Testing ActionExecutor...")
    
    executor = ActionExecutor()
    
    # Test hotkey action (Win+D = minimize all)
    result = executor.execute_action({
        "type": "hotkey",
        "keys": ["win", "d"]
    })
    print(f"Hotkey result: {result}")
    
    # Test action validation
    valid, msg = executor.validate_action({
        "type": "launch",
        "path": "notepad.exe"
    })
    print(f"Validation: {valid} - {msg}")
