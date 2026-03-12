"""
GestureGuard - State Machine Module
Main orchestration logic for authentication flow
FR-2: Authentication Flow
"""

import time
import threading
from enum import Enum
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass

import numpy as np
import cv2

from core.detector import CameraMonitor, normalize_signature
from core.authenticator import Authenticator
from core.actions import ActionExecutor, lock_workstation


class SystemState(Enum):
    """System states"""
    IDLE = "idle"
    WATCHING = "watching"           # Monitoring for trigger
    PIN_ENTRY = "pin_entry"        # Awaiting PIN input
    GESTURE_CAPTURE = "gesture_capture"  # Capturing gesture
    AUTHENTICATING = "authenticating"    # Running DTW match
    ACTION_EXECUTION = "action_execution" # Running profile actions
    LOCKED = "locked"              # System locked (too many failures)


@dataclass
class AuthConfig:
    """Authentication configuration"""
    pin_timeout: float = 10.0       # PIN entry timeout (seconds)
    gesture_capture_duration: float = 3.0  # Max gesture capture time
    gesture_min_points: int = 30    # Minimum gesture points


class GestureStateMachine:
    """
    Main state machine orchestrating the authentication flow.
    
    Authentication Sequence (from PRD):
    1. Trigger Detection (Person/Hand proximity)
       ↓
    2. PIN Entry (10-second timeout)
       ↓ (if valid PIN)
    3. Gesture Capture (3-second window)
       ↓
    4. DTW Matching (all profiles)
       ↓
    5. Action Execution OR Failure Response
    """
    
    def __init__(
        self,
        camera_index: int = 0,
        config: Optional[AuthConfig] = None,
        on_state_change: Optional[Callable[[SystemState], None]] = None,
        on_pin_required: Optional[Callable[[], str]] = None,
        on_gesture_capture: Optional[Callable[[], None]] = None,
        on_auth_complete: Optional[Callable[[bool, str], None]] = None
    ):
        """
        Initialize state machine.
        
        Args:
            camera_index: Camera device index
            config: Authentication configuration
            on_state_change: Callback when state changes
            on_pin_required: Callback to get PIN from user (should return PIN string)
            on_gesture_capture: Callback when gesture capture starts
            on_auth_complete: Callback when authentication completes (success, message)
        """
        self.config = config or AuthConfig()
        
        # Components
        self.camera = CameraMonitor(camera_index=camera_index)
        self.authenticator = Authenticator()
        self.action_executor = ActionExecutor()
        
        # State
        self.state = SystemState.IDLE
        self.previous_state = SystemState.IDLE
        self.is_running = False
        
        # Authentication data
        self.current_pin = ""
        self.current_gesture: List[List[float]] = []
        self.auth_start_time = 0
        
        # Callbacks
        self.on_state_change = on_state_change
        self.on_pin_required = on_pin_required
        self.on_gesture_capture = on_gesture_capture
        self.on_auth_complete = on_auth_complete
        
        # Thread control
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Statistics
        self.stats = {
            "auth_attempts": 0,
            "auth_successes": 0,
            "auth_failures": 0,
            "last_auth_time": None,
            "average_auth_time": 0
        }
    
    def start(self) -> bool:
        """Start the state machine"""
        if self.is_running:
            return True
        
        # Start camera
        if not self.camera.start():
            print("Failed to start camera")
            return False
        
        self.is_running = True
        self._stop_event.clear()
        
        # Start worker thread
        self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._worker_thread.start()
        
        self._set_state(SystemState.WATCHING)
        print("GestureGuard started - watching for authentication triggers")
        
        return True
    
    def stop(self) -> None:
        """Stop the state machine"""
        self.is_running = False
        self._stop_event.set()
        
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
        
        self.camera.stop()
        self._set_state(SystemState.IDLE)
        print("GestureGuard stopped")
    
    def _set_state(self, new_state: SystemState) -> None:
        """Change system state"""
        if self.state != new_state:
            self.previous_state = self.state
            self.state = new_state
            print(f"State: {self.previous_state.value} → {self.state.value}")
            
            if self.on_state_change:
                self.on_state_change(new_state)
    
    def _run_loop(self) -> None:
        """Main worker loop"""
        while not self._stop_event.is_set():
            if self.state == SystemState.WATCHING:
                self._handle_watching()
            elif self.state == SystemState.PIN_ENTRY:
                self._handle_pin_entry()
            elif self.state == SystemState.GESTURE_CAPTURE:
                self._handle_gesture_capture()
            elif self.state == SystemState.AUTHENTICATING:
                self._handle_authenticating()
            elif self.state == SystemState.LOCKED:
                self._handle_locked()
            
            # Small delay to prevent CPU spinning
            time.sleep(0.01)
    
    def _handle_watching(self) -> None:
        """Handle watching state - monitor for trigger"""
        # Get frame and detect hands
        frame, hands_data, trigger = self.camera.process_frame()
        
        if frame is not None:
            # Display frame (in production, this would go to a GUI)
            pass
        
        # Check for trigger condition
        if trigger:
            self._start_authentication()
    
    def _start_authentication(self) -> None:
        """Start authentication flow"""
        self.auth_start_time = time.time()
        self.current_pin = ""
        self.current_gesture = []
        
        self.stats["auth_attempts"] += 1
        self._set_state(SystemState.PIN_ENTRY)
        
        print("Authentication triggered - awaiting PIN")
    
    def _handle_pin_entry(self) -> None:
        """Handle PIN entry state"""
        # Check timeout
        elapsed = time.time() - self.auth_start_time
        if elapsed > self.config.pin_timeout:
            print(f"PIN timeout ({self.config.pin_timeout}s)")
            self._auth_failed("PIN entry timeout")
            return
        
        # Only show overlay once when entering this state
        if not hasattr(self, '_pin_overlay_shown'):
            self._pin_overlay_shown = True
            
            # Import here to avoid tkinter import errors in headless environments
            try:
                from gui.pin_overlay import PINEntryOverlay
                
                # Create callback for PIN submission
                def on_pin_submit(pin):
                    self.current_pin = pin
                    self._pin_received = True
                
                def on_pin_cancel():
                    self._auth_failed("PIN entry cancelled")
                
                def on_pin_timeout():
                    self._auth_failed("PIN entry timeout")
                
                # Show PIN overlay (non-blocking with threading)
                import threading
                
                def show_overlay():
                    overlay = PINEntryOverlay(
                        timeout=self.config.pin_timeout,
                        on_submit=on_pin_submit,
                        on_cancel=on_pin_cancel,
                        on_timeout=on_pin_timeout
                    )
                    result = overlay.show()
                    
                    # Signal that overlay is closed
                    self._pin_overlay_closed = True
                
                # Start overlay in separate thread
                overlay_thread = threading.Thread(target=show_overlay, daemon=True)
                overlay_thread.start()
                
            except ImportError as e:
                print(f"Warning: GUI not available ({e}), using callback fallback")
                # Fall back to callback
                if self.on_pin_required:
                    pin = self.on_pin_required()
                    if pin:
                        self.current_pin = pin
                        self._pin_received = True
                else:
                    print("Error: No PIN input method available")
                    self._auth_failed("No PIN input method")
        
        # Check if PIN was received
        if hasattr(self, '_pin_received') and self._pin_received:
            print(f"PIN received: {'*' * len(self.current_pin)}")
            self._set_state(SystemState.GESTURE_CAPTURE)
            self.gesture_capture_start = time.time()
            self.accumulated_gesture = []
            
            # Clean up flags
            delattr(self, '_pin_overlay_shown')
            delattr(self, '_pin_received')
            
            if self.on_gesture_capture:
                self.on_gesture_capture()
    
    def _handle_gesture_capture(self) -> None:
        """Handle gesture capture state - accumulate gesture frames over time"""
        # Check if we just entered this state
        if not hasattr(self, 'gesture_capture_start'):
            self.gesture_capture_start = time.time()
            self.accumulated_gesture = []
            print("Gesture capture started - perform your gesture now!")
        
        # Check timeout
        elapsed = time.time() - self.gesture_capture_start
        if elapsed > self.config.gesture_capture_duration:
            print(f"Gesture capture complete ({self.config.gesture_capture_duration}s)")
            
            # Check if we captured enough points
            if len(self.accumulated_gesture) >= self.config.gesture_min_points:
                # Normalize the full gesture
                gesture_array = np.array(self.accumulated_gesture)
                normalized = normalize_signature(gesture_array)
                self.current_gesture = normalized
                
                print(f"Captured {len(self.accumulated_gesture)} gesture points")
                
                # Move to authentication
                self._set_state(SystemState.AUTHENTICATING)
                self._perform_authentication()
            else:
                self._auth_failed(f"Gesture too short: {len(self.accumulated_gesture)} points (need {self.config.gesture_min_points})")
            
            # Clean up
            if hasattr(self, 'gesture_capture_start'):
                delattr(self, 'gesture_capture_start')
            return
        
        # Continue capturing frames
        frame = self.camera.get_frame()
        if frame is not None:
            hands_data = self.camera.detect_hands(frame)
            
            if hands_data:
                # Get the first hand's landmarks
                landmarks = hands_data[0].landmarks
                self.accumulated_gesture.append(landmarks)
                
                # Show progress
                if len(self.accumulated_gesture) % 10 == 0:
                    print(f"Capturing... {len(self.accumulated_gesture)} points ({elapsed:.1f}s)")
            else:
                # No hand detected - warn user
                if len(self.accumulated_gesture) == 0 and elapsed > 1.0:
                    print("Warning: No hand detected! Show your hand to the camera.")
    
    def _perform_authentication(self) -> None:
        """Perform DTW authentication (called from gesture capture)"""
        # This runs the actual authentication
        # Called automatically after gesture capture completes
        pass  # The actual work is done in _handle_authenticating
    
    def _handle_authenticating(self) -> None:
        """Handle authentication (DTW matching)"""
        # Convert gesture to numpy array if needed
        if isinstance(self.current_gesture, list):
            gesture_array = np.array(self.current_gesture)
        else:
            gesture_array = self.current_gesture
        
        print(f"Authenticating with gesture ({len(gesture_array)} points)...")
        
        # Authenticate
        profile, status = self.authenticator.authenticate(
            self.current_pin,
            gesture_array
        )
        
        # Update stats
        if profile:
            self.stats["auth_successes"] += 1
            self._auth_success(profile, status)
        else:
            self.stats["auth_failures"] += 1
            self._auth_failed(status)
    
    def _auth_success(self, profile, message: str) -> None:
        """Handle successful authentication"""
        print(f"✓ Authentication successful: {message}")
        
        # Execute profile actions
        if profile.actions:
            self._set_state(SystemState.ACTION_EXECUTION)
            
            print(f"Executing {len(profile.actions)} actions...")
            results = self.action_executor.execute_actions(profile.actions)
            
            for result in results:
                print(f"  {result}")
        
        # Update stats
        auth_time = time.time() - self.auth_start_time
        self.stats["last_auth_time"] = time.time()
        
        # Calculate running average
        n = self.stats["auth_attempts"]
        avg = self.stats["average_auth_time"]
        self.stats["average_auth_time"] = (avg * (n - 1) + auth_time) / n
        
        # Notify callback
        if self.on_auth_complete:
            self.on_auth_complete(True, message)
        
        # Return to watching
        self._set_state(SystemState.WATCHING)
    
    def _auth_failed(self, message: str) -> None:
        """Handle authentication failure"""
        print(f"✗ Authentication failed: {message}")
        
        # Lock if too many failures
        if self.authenticator.is_locked:
            print("System locked due to too many failed attempts")
            self._set_state(SystemState.LOCKED)
        else:
            # Return to watching
            if self.on_auth_complete:
                self.on_auth_complete(False, message)
            
            self._set_state(SystemState.WATCHING)
    
    def _handle_gesture_capture_direct(self, duration: float = 3.0) -> Optional[List[List[float]]]:
        """
        Capture gesture directly (synchronous, for use with GUI).
        
        Args:
            duration: Maximum capture duration in seconds
            
        Returns:
            Normalized gesture data or None
        """
        gesture_frames: List[np.ndarray] = []
        start_time = time.time()
        
        print(f"Capturing gesture ({duration}s)...")
        
        while time.time() - start_time < duration:
            gesture = self.camera.get_current_gesture()
            
            if gesture is not None:
                gesture_frames.append(gesture)
            
            time.sleep(0.033)  # ~30 FPS
        
        if not gesture_frames:
            print("No gesture captured")
            return None
        
        # Flatten all frames
        flat_gesture = [frame.tolist() for frame in gesture_frames]
        all_points = [point for frame in flat_gesture for point in frame]
        
        if len(all_points) < self.config.gesture_min_points:
            print(f"Gesture too short: {len(all_points)} points")
            return None
        
        # Normalize
        gesture_array = np.array(all_points)
        normalized = normalize_signature(gesture_array)
        
        print(f"Captured {len(all_points)} points")
        return normalized.tolist()
    
    def _handle_locked(self) -> None:
        """Handle locked state"""
        # In locked state, just wait
        # Could implement auto-unlock after time
        time.sleep(1.0)
        
        # For now, allow manual unlock after delay
        if self.authenticator.failed_attempts < self.authenticator.max_failed_attempts:
            self.authenticator.is_locked = False
            print("System unlocked")
            self._set_state(SystemState.WATCHING)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get authentication statistics"""
        return self.stats.copy()
    
    def manual_authenticate(self, pin: str, gesture: Optional[np.ndarray] = None) -> tuple:
        """
        Manual authentication entry point (for testing or GUI).
        
        Args:
            pin: PIN to verify
            gesture: Gesture data (optional, will capture if not provided)
            
        Returns:
            Tuple of (profile or None, status message)
        """
        if gesture is None:
            gesture = self._handle_gesture_capture_direct()
            if gesture is None:
                return None, "No gesture captured"
        
        gesture_array = np.array(gesture)
        
        return self.authenticator.authenticate(pin, gesture_array)
    
    def process_frame(self) -> tuple:
        """
        Process a single frame (for manual loop control).
        
        Returns:
            Tuple of (frame, hands_data, trigger_activated)
        """
        return self.camera.process_frame()


def create_cli_authenticator() -> GestureStateMachine:
    """Create state machine with CLI callbacks"""
    
    def get_pin_cli() -> str:
        """Get PIN from CLI input"""
        import sys
        pin = input("Enter PIN: ")
        return pin
    
    state_machine = GestureStateMachine(
        on_pin_required=get_pin_cli,
        on_state_change=lambda s: print(f"State: {s.value}"),
        on_auth_complete=lambda s, m: print(f"Auth: {s} - {m}")
    )
    
    return state_machine


if __name__ == "__main__":
    print("Testing GestureStateMachine...")
    
    # Simple test
    sm = GestureStateMachine()
    
    # Note: This requires camera and will run the full state machine
    # For testing, use manual_authenticate
    
    print("Starting camera test (press 'q' to quit)...")
    
    if sm.start():
        try:
            while True:
                frame, hands, trigger = sm.process_frame()
                
                if frame is not None:
                    cv2.imshow("Test", frame)
                
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                    
        finally:
            sm.stop()
            cv2.destroyAllWindows()
