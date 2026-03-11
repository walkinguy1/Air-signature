"""
GestureGuard - Camera Monitor and Hand Detection Module
Uses MediaPipe Hands for real-time hand landmark detection
"""

import cv2
import mediapipe as mp
import numpy as np
import time
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass


# Configuration constants (from PRD)
TRIGGER_HAND_COUNT = 2        # Number of hands to trigger authentication
TRIGGER_DURATION = 2.0        # Seconds of multiple hands before trigger
TRIGGER_PROXIMITY = 0.3       # Normalized distance threshold
MIN_DETECTION_CONFIDENCE = 0.7
MIN_TRACKING_CONFIDENCE = 0.5
TARGET_FPS = 30


@dataclass
class HandData:
    """Container for hand landmark data"""
    landmarks: np.ndarray      # Shape: (21, 3) - x, y, z coordinates
    handedness: str           # "Left" or "Right"
    timestamp: float         # Unix timestamp
    frame_id: int             # Frame counter


class CameraMonitor:
    """
    Monitors camera feed for hand detection and trigger conditions.
    FR-1.1: Capture 3D hand landmarks at 30 FPS using webcam
    FR-2.1: Trigger authentication when detecting >1 hand for >2 seconds
    """
    
    def __init__(self, camera_index: int = 0, resolution: Tuple[int, int] = (1280, 720)):
        """
        Initialize camera monitor.
        
        Args:
            camera_index: Index of camera to use (default: 0)
            resolution: Camera resolution as (width, height)
        """
        self.camera_index = camera_index
        self.resolution = resolution
        
        # MediaPipe Hands initialization
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=10,
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
            model_complexity=1  # Full palm model for better accuracy
        )
        
        # Camera capture
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_running = False
        
        # Detection state
        self.hand_count_history: List[Tuple[int, float]] = []  # (hand_count, timestamp)
        self.last_trigger_time: Optional[float] = None
        self.trigger_condition_met = False
        
        # Frame tracking
        self.frame_count = 0
        self.fps = 0
        self._fps_start_time = None
        
        # Callback for trigger events
        self.on_trigger_callback = None
        
    def start(self) -> bool:
        """Start camera capture"""
        self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            print(f"Error: Could not open camera {self.camera_index}")
            return False
        
        # Set camera resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
        
        self.is_running = True
        self._fps_start_time = time.time()
        print(f"Camera started: {self.resolution[0]}x{self.resolution[1]} @ {TARGET_FPS} FPS")
        return True
    
    def stop(self) -> None:
        """Stop camera capture"""
        self.is_running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        print("Camera stopped")
    
    def get_frame(self) -> Optional[np.ndarray]:
        """Capture and return a single frame"""
        if not self.cap or not self.is_running:
            return None
        
        ret, frame = self.cap.read()
        if not ret:
            return None
        
        # Flip frame horizontally for mirror effect
        frame = cv2.flip(frame, 1)
        self.frame_count += 1
        
        # Update FPS
        elapsed = time.time() - self._fps_start_time
        if elapsed > 0:
            self.fps = self.frame_count / elapsed
            
        return frame
    
    def detect_hands(self, frame: np.ndarray) -> List[HandData]:
        """
        Detect hands in frame and return landmark data.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            List of HandData objects for each detected hand
        """
        # Convert to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False  # Optimize for read-only
        
        # Process frame with MediaPipe
        results = self.hands.process(rgb_frame)
        
        hands_data = []
        timestamp = time.time()
        
        if results.multi_hand_landmarks and results.multi_handedness:
            for idx, (landmarks, handedness) in enumerate(
                zip(results.multi_hand_landmarks, results.multi_handedness)
            ):
                # Extract landmark coordinates
                landmarks_array = np.array([[lm.x, lm.y, lm.z] for lm in landmarks.landmark])
                
                hand_data = HandData(
                    landmarks=landmarks_array,
                    handedness=handedness.classification[0].label,
                    timestamp=timestamp,
                    frame_id=self.frame_count
                )
                hands_data.append(hand_data)
                
        return hands_data
    
    def check_trigger_condition(self, hand_count: int) -> bool:
        """
        Check if trigger condition is met (>1 hand for >2 seconds).
        
        Args:
            hand_count: Number of hands currently detected
            
        Returns:
            True if trigger condition is met
        """
        current_time = time.time()
        
        # Add current detection to history
        self.hand_count_history.append((hand_count, current_time))
        
        # Clean up old history (keep last 10 seconds)
        cutoff_time = current_time - 10.0
        self.hand_count_history = [
            (hc, ts) for hc, ts in self.hand_count_history 
            if ts > cutoff_time
        ]
        
        # Check for trigger condition
        recent_detections = [
            hc for hc, ts in self.hand_count_history 
            if ts > current_time - TRIGGER_DURATION
        ]
        
        if len(recent_detections) >= int(TARGET_FPS * TRIGGER_DURATION * 0.8):
            # At least 80% of frames in duration window had >1 hands
            trigger_met = all(hc >= TRIGGER_HAND_COUNT for hc in recent_detections)
            
            if trigger_met and not self.trigger_condition_met:
                self.last_trigger_time = current_time
                self.trigger_condition_met = True
                print(f"Trigger condition MET: {hand_count} hands for {TRIGGER_DURATION}s")
                return True
            elif not trigger_met:
                self.trigger_condition_met = False
                
        return False
    
    def get_hand_skeleton(self, frame: np.ndarray, hands_data: List[HandData]) -> np.ndarray:
        """
        Draw hand skeleton overlay on frame.
        
        Args:
            frame: Original frame
            hands_data: List of detected hands
            
        Returns:
            Frame with skeleton overlay
        """
        output_frame = frame.copy()
        
        for hand_landmarks in hands_data:
            # Draw landmarks
            self.mp_drawing.draw_landmarks(
                output_frame,
                hand_landmarks.landmarks,
                self.mp_hands.HAND_CONNECTIONS,
                self.mp_drawing_styles.get_default_hand_landmarks_style(),
                self.mp_drawing_styles.get_default_hand_connections_style()
            )
        
        return output_frame
    
    def process_frame(self, draw_skeleton: bool = True) -> Tuple[Optional[np.ndarray], List[HandData], bool]:
        """
        Process a single frame: detect hands, check trigger, optionally draw skeleton.
        
        Returns:
            Tuple of (frame, hands_data, trigger_activated)
        """
        frame = self.get_frame()
        if frame is None:
            return None, [], False
        
        # Detect hands
        hands_data = self.detect_hands(frame)
        
        # Check trigger condition
        trigger_activated = False
        if len(hands_data) >= TRIGGER_HAND_COUNT:
            trigger_activated = self.check_trigger_condition(len(hands_data))
        
        # Draw skeleton if requested
        if draw_skeleton and hands_data:
            frame = self.get_hand_skeleton(frame, hands_data)
        
        # Add UI overlay
        frame = self._add_ui_overlay(frame, hands_data)
        
        return frame, hands_data, trigger_activated
    
    def _add_ui_overlay(self, frame: np.ndarray, hands_data: List[HandData]) -> np.ndarray:
        """Add UI information overlay to frame"""
        h, w = frame.shape[:2]
        
        # Status bar background
        cv2.rectangle(frame, (0, 0), (w, 40), (0, 0, 0), -1)
        cv2.putText(frame, f"GestureGuard | Hands: {len(hands_data)} | FPS: {self.fps:.1f}", 
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        
        # Trigger status indicator
        if self.trigger_condition_met:
            cv2.circle(frame, (w - 30, 20), 10, (0, 0, 255), -1)
            cv2.putText(frame, "TRIGGER", (w - 100, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        
        return frame
    
    def get_current_gesture(self) -> Optional[np.ndarray]:
        """
        Get current hand gesture as normalized coordinates.
        Used for live gesture capture during authentication.
        
        Returns:
            Array of shape (N, 3) with normalized x, y, z coordinates
        """
        frame = self.get_frame()
        if frame is None:
            return None
        
        hands_data = self.detect_hands(frame)
        
        if not hands_data:
            return None
        
        # Return first hand's landmarks
        return hands_data[0].landmarks


def normalize_signature(raw_coords: np.ndarray) -> np.ndarray:
    """
    Normalize gesture coordinates using vector displacement from start point.
    FR-1.2: Normalize signatures using vector displacement (Δx, Δy, Δz)
    
    Args:
        raw_coords: Array of shape (N, 3) with x, y, z coordinates
        
    Returns:
        Normalized array of same shape
    """
    if len(raw_coords) == 0:
        return raw_coords
    
    start_point = raw_coords[0]
    normalized = raw_coords - start_point
    
    return normalized


def get_gesture_duration(hand_data: HandData, fps: int = TARGET_FPS) -> float:
    """Calculate approximate gesture duration from frame count"""
    return hand_data.frame_id / fps


# For testing standalone
if __name__ == "__main__":
    print("Testing CameraMonitor...")
    
    monitor = CameraMonitor()
    if monitor.start():
        print("Press 'q' to quit, 'r' to start recording")
        
        recording = False
        gesture_data = []
        
        while True:
            frame, hands_data, trigger = monitor.process_frame()
            
            if frame is None:
                break
            
            cv2.imshow("GestureGuard", frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                recording = not recording
                if recording:
                    gesture_data = []
                    print("Recording started... (press 'r' to stop)")
                else:
                    print(f"Recording stopped. Captured {len(gesture_data)} frames")
                    
            if recording and hands_data:
                gesture_data.append(hands_data[0].landmarks.copy())
                
        monitor.stop()
        cv2.destroyAllWindows()
