"""
GestureGuard - Gesture Recorder Tool
Captures and saves gesture signatures for profile creation
FR-1.1: Capture 3D hand landmarks at 30 FPS
FR-1.4: Allow users to record 3-5 samples per signature
"""

import cv2
import sys
import os
import json
import time
import numpy as np
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.detector import CameraMonitor, normalize_signature
from core.authenticator import MIN_SIGNATURE_POINTS


class GestureRecorder:
    """
    Records user gestures for profile creation.
    FR-1.4: Record 3-5 samples per signature
    """
    
    def __init__(self, camera_index: int = 0):
        self.camera = CameraMonitor(camera_index=camera_index)
        self.samples: list = []
        self.is_recording = False
        self.current_gesture: list = []
        
        # Recording parameters
        self.min_duration = 1.5  # seconds
        self.max_duration = 4.0  # seconds
        self.min_points = int(30 * self.min_duration)  # ~30 FPS
        self.max_points = int(30 * self.max_duration)
        
        # UI state
        self.recording_start_time = 0
        self.countdown = 3  # Countdown before recording
    
    def start(self) -> bool:
        """Initialize camera and start recording interface"""
        return self.camera.start()
    
    def stop(self) -> None:
        """Stop recording and release camera"""
        self.camera.stop()
    
    def capture_sample(self) -> bool:
        """
        Capture a single gesture sample.
        
        Press 'r' to start/stop recording a sample.
        Recording automatically stops after max_duration or when hand is removed.
        
        Returns:
            True if sample was captured successfully
        """
        print("\n" + "="*50)
        print("GESTURE RECORDING")
        print("="*50)
        print(f"Instructions:")
        print(f"  - Press 'r' to start/stop recording a gesture")
        print(f"  - Press 'q' to quit recording mode")
        print(f"  - Press 's' to save all samples to file")
        print(f"  - Press 'c' to clear all samples")
        print(f"\nRequirements:")
        print(f"  - Record 3-5 samples per gesture")
        print(f"  - Each sample: {self.min_duration}-{self.max_duration} seconds")
        print(f"  - Minimum {self.min_points} coordinate points per sample")
        print("="*50 + "\n")
        
        while True:
            frame, hands_data, trigger = self.camera.process_frame()
            
            if frame is None:
                break
            
            # Recording state
            if self.is_recording:
                elapsed = time.time() - self.recording_start_time
                
                # Check duration
                if elapsed > self.max_duration:
                    print(f"Max duration reached ({self.max_duration}s) - stopping")
                    self._stop_recording()
                
                # Capture hand data
                elif hands_data:
                    # Get the first hand's landmarks
                    landmarks = hands_data[0].landmarks
                    self.current_gesture.append(landmarks.tolist())
                
                # Draw recording indicator
                cv2.circle(frame, (frame.shape[1] - 50, 50), 20, (0, 0, 255), -1)
                cv2.putText(frame, f"REC {elapsed:.1f}s", 
                           (frame.shape[1] - 120, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            
            # Display sample count
            cv2.putText(frame, f"Samples: {len(self.samples)}/5", 
                       (10, frame.shape[0] - 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Show frame
            cv2.imshow("GestureGuard - Recorder", frame)
            
            # Handle keypress
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                return False
            
            elif key == ord('r'):
                if self.is_recording:
                    self._stop_recording()
                else:
                    self._start_recording()
            
            elif key == ord('s'):
                if self.samples:
                    return True
            
            elif key == ord('c'):
                self.samples = []
                print("Samples cleared")
        
        return False
    
    def _start_recording(self) -> None:
        """Start recording a new sample"""
        self.is_recording = True
        self.recording_start_time = time.time()
        self.current_gesture = []
        
        # Countdown before actual recording
        print("\nGet ready... Recording starts in 3 seconds")
        print("Perform your gesture now!")
        
        # Show countdown on screen
        for i in range(3, 0, -1):
            frame = self.camera.get_frame()
            if frame is not None:
                cv2.putText(frame, f"{i}", 
                           (frame.shape[1]//2 - 50, frame.shape[0]//2),
                           cv2.FONT_HERSHEY_SIMPLEX, 5, (0, 255, 0), 10)
                cv2.imshow("GestureGuard - Recorder", frame)
                cv2.waitKey(1000)
        
        self.recording_start_time = time.time()
        print("Recording...")
    
    def _stop_recording(self) -> None:
        """Stop recording and save sample if valid"""
        self.is_recording = False
        
        # Check if sample is valid
        total_points = sum(len(frame) for frame in self.current_gesture)
        
        if total_points < self.min_points:
            print(f"❌ Sample too short: {total_points} points (need {self.min_points})")
            self.current_gesture = []
            return
        
        # Flatten to list of [x, y, z] coordinates
        flat_gesture = [point for frame in self.current_gesture for point in frame]
        
        # Normalize the gesture
        normalized = normalize_signature(np.array(flat_gesture))
        
        self.samples.append(normalized.tolist())
        print(f"✓ Sample {len(self.samples)} saved ({total_points} points)")
        
        self.current_gesture = []
        
        if len(self.samples) >= 5:
            print("Maximum samples (5) reached!")
    
    def save_samples(self, filename: str = None) -> str:
        """
        Save recorded samples to JSON file.
        
        Args:
            filename: Output filename (optional)
            
        Returns:
            Path to saved file
        """
        if not self.samples:
            print("No samples to save!")
            return ""
        
        if filename is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"gesture_{timestamp}.json"
        
        filepath = Path("profiles") / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "samples": self.samples,
            "sample_count": len(self.samples),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "points_per_sample": [len(s) for s in self.samples]
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Saved {len(self.samples)} samples to {filepath}")
        
        # Print stats
        avg_points = sum(data["points_per_sample"]) / len(self.samples)
        print(f"  Average points per sample: {avg_points:.0f}")
        
        return str(filepath)
    
    def load_samples(self, filepath: str) -> bool:
        """
        Load samples from JSON file.
        
        Args:
            filepath: Path to JSON file
            
        Returns:
            True if loaded successfully
        """
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.samples = data.get("samples", [])
            print(f"✓ Loaded {len(self.samples)} samples from {filepath}")
            return True
            
        except Exception as e:
            print(f"Error loading samples: {e}")
            return False
    
    def get_samples(self) -> list:
        """Get recorded samples"""
        return self.samples
    
    def clear_samples(self) -> None:
        """Clear all recorded samples"""
        self.samples = []
        print("Samples cleared")


def record_gesture_profile():
    """
    Interactive gesture recording workflow for profile creation.
    """
    print("\n" + "="*60)
    print("GESTUREGUARD - GESTURE RECORDING WIZARD")
    print("="*60)
    print("\nThis wizard will help you record your unique gesture signature.")
    print("You'll record 3-5 samples of the same gesture.\n")
    
    recorder = GestureRecorder()
    
    if not recorder.start():
        print("Error: Could not start camera")
        return None
    
    try:
        # Capture samples
        recorder.capture_sample()
        
        if not recorder.samples:
            print("No samples recorded")
            return None
        
        # Save samples
        filepath = recorder.save_samples()
        
        print("\n" + "="*60)
        print("RECORDING COMPLETE")
        print("="*60)
        print(f"Samples saved to: {filepath}")
        print(f"\nNext steps:")
        print("  1. Use these samples with the profile creation wizard")
        print("  2. Or run: python -m tools.tester to test matching")
        
        return filepath
        
    finally:
        recorder.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    record_gesture_profile()
