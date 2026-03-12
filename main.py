#!/usr/bin/env python3
"""
GestureGuard - Main Entry Point
Gesture-Authenticated Environment Manager

Usage:
    python main.py                    # Start in watch mode
    python main.py --record           # Record new gesture
    python main.py --create-profile   # Create new profile
    python main.py --list-profiles    # List all profiles
    python main.py --test             # Test authentication
"""

import sys
import os
import argparse
import time
import cv2
import numpy as np
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from core.detector import CameraMonitor
from core.authenticator import Authenticator
from core.actions import ActionExecutor, lock_workstation
from core.state_machine import GestureStateMachine, SystemState
from tools.recorder import GestureRecorder


def print_banner():
    """Print startup banner"""
    print("=" * 60)
    print("  GestureGuard - Gesture-Authenticated Environment Manager")
    print("  Version 1.0 - Gold Medal Edition")
    print("=" * 60)
    print()


def start_watch_mode(args):
    """Start in continuous watch mode"""
    print("Starting GestureGuard in watch mode...")
    print("Press 'q' to quit, 'r' to record new gesture\n")
    
    # Create state machine
    sm = GestureStateMachine(
        camera_index=args.camera,
        on_state_change=lambda s: print(f"[State] {s.value}"),
        on_auth_complete=lambda s, m: print(f"[Auth] {'SUCCESS' if s else 'FAILED'}: {m}")
    )
    
    if not sm.start():
        print("Failed to start GestureGuard")
        return 1
    
    try:
        while True:
            frame, hands, trigger = sm.process_frame()
            
            if frame is not None:
                # Add status overlay
                status = f"Mode: {sm.state.value} | Hands: {len(hands)}"
                cv2.putText(frame, status, (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                cv2.imshow("GestureGuard", frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                print("Starting recording...")
                # Could trigger profile creation here
                
    finally:
        sm.stop()
        cv2.destroyAllWindows()
    
    return 0


def record_gesture(args):
    """Record a new gesture"""
    print("Starting gesture recorder...")
    
    recorder = GestureRecorder(camera_index=args.camera)
    
    if not recorder.start():
        print("Failed to start camera")
        return 1
    
    try:
        success = recorder.capture_sample()
        
        if success and recorder.samples:
            filename = f"gesture_{int(time.time())}.json"
            recorder.save_samples(filename)
            print(f"\nGesture saved to: profiles/{filename}")
            print("Use this with profile creation to add to a profile.")
        else:
            print("No samples recorded")
            
    finally:
        recorder.stop()
        cv2.destroyAllWindows()
    
    return 0


def create_profile(args):
    """Create a new profile"""
    print("=" * 60)
    print("GESTUREGUARD - CREATE NEW PROFILE")
    print("=" * 60)
    print()
    
    # Get profile info
    name = input("Profile name: ").strip()
    if not name:
        print("Profile name required")
        return 1
    
    pin = input("PIN (4 digits): ").strip()
    if len(pin) != 4 or not pin.isdigit():
        print("PIN must be 4 digits")
        return 1
    
    # Record gesture
    print("\n--- Recording Gesture ---")
    print("You'll record 3-5 samples of your unique gesture.")
    print("Press 'r' to start/stop each sample, 's' to save when done.\n")
    
    recorder = GestureRecorder(camera_index=args.camera)
    
    if not recorder.start():
        print("Failed to start camera")
        return 1
    
    try:
        success = recorder.capture_sample()
        
        if not success or not recorder.samples:
            print("No gesture samples recorded")
            return 1
        
        # Get actions
        print("\n--- Profile Actions ---")
        print("What actions should this profile execute?")
        print("Examples:")
        print("  1. Minimize all (Win+D)")
        print("  2. Launch application")
        print("  3. Custom script")
        
        actions = []
        while True:
            choice = input("\nAdd action? (y/n): ").strip().lower()
            if choice != 'y':
                break
            
            action_type = input("Action type (hotkey/launch/script): ").strip().lower()
            
            if action_type == "hotkey":
                keys = input("Keys (e.g., win,d): ").strip()
                actions.append({
                    "type": "hotkey",
                    "keys": keys.split(",")
                })
            elif action_type == "launch":
                path = input("Application path: ").strip()
                actions.append({
                    "type": "launch",
                    "path": path
                })
            elif action_type == "script":
                path = input("Script path: ").strip()
                actions.append({
                    "type": "script",
                    "path": path
                })
            
            print(f"  Added: {action_type}")
        
        # Create profile
        auth = Authenticator()
        
        # Check distinctness
        is_distinct, msg = auth.check_profile_distinctness(recorder.samples)
        if not is_distinct:
            print(f"\nWarning: {msg}")
            proceed = input("Proceed anyway? (y/n): ").strip().lower()
            if proceed != 'y':
                return 1
        
        profile = auth.create_profile(
            name=name,
            pin=pin,
            signature_samples=recorder.samples,
            actions=actions
        )
        
        print(f"\n✓ Profile '{name}' created successfully!")
        print(f"  Profile ID: {profile.profile_id}")
        print(f"  Samples: {len(recorder.samples)}")
        print(f"  Actions: {len(actions)}")
        
    finally:
        recorder.stop()
        cv2.destroyAllWindows()
    
    return 0


def list_profiles(args):
    """List all profiles"""
    auth = Authenticator()
    profiles = auth.profiles
    
    if not profiles:
        print("No profiles found. Create one with --create-profile")
        return 0
    
    print(f"\nFound {len(profiles)} profile(s):\n")
    
    for i, profile in enumerate(profiles, 1):
        print(f"{i}. {profile.name}")
        print(f"   ID: {profile.profile_id}")
        print(f"   Created: {profile.created_at}")
        print(f"   Last used: {profile.last_used or 'Never'}")
        print(f"   Actions: {len(profile.actions)}")
        print()
    
    return 0


def test_auth(args):
    """Test authentication flow"""
    print("=" * 60)
    print("GESTUREGUARD - AUTHENTICATION TEST")
    print("=" * 60)
    print("\nThis will test the full authentication flow.")
    print("You'll enter your PIN and perform your gesture.\n")
    
    auth = Authenticator()
    
    if not auth.profiles:
        print("No profiles found. Create one first with --create-profile")
        return 1
    
    # Show available profiles
    print("Available profiles:")
    for i, p in enumerate(auth.profiles, 1):
        print(f"  {i}. {p.name}")
    
    # Get PIN
    pin = input("\nEnter PIN: ").strip()
    
    # Capture gesture
    print("\nPerform your gesture in front of the camera...")
    print("Press any key to start, then perform gesture for 3 seconds...")
    
    camera = CameraMonitor(camera_index=args.camera)
    
    if not camera.start():
        print("Failed to start camera")
        return 1
    
    try:
        # Wait for key press
        cv2.waitKey(0)
        
        print("\nGet ready to perform your gesture...")
        print("3...")
        time.sleep(1)
        print("2...")
        time.sleep(1)
        print("1...")
        time.sleep(1)
        print("GO! Perform your gesture NOW!")
        
        # Capture gesture - accumulate frames over time
        gesture_frames = []
        start_time = time.time()
        last_print = 0
        
        while time.time() - start_time < 3.0:
            frame = camera.get_frame()
            if frame is not None:
                hands_data = camera.detect_hands(frame)
                
                if hands_data:
                    # Add landmarks from first hand
                    gesture_frames.append(hands_data[0].landmarks)
                    
                    # Show progress every 0.5 seconds
                    elapsed = time.time() - start_time
                    if elapsed - last_print > 0.5:
                        print(f"  ✓ Capturing... {len(gesture_frames)} points ({elapsed:.1f}s)")
                        last_print = elapsed
                else:
                    # Warn if no hand detected
                    elapsed = time.time() - start_time
                    if elapsed > 0.5 and len(gesture_frames) == 0:
                        print("  ⚠ No hand detected! Show your hand to the camera!")
            
            # Show the frame so you can see yourself
            if frame is not None:
                cv2.imshow("GestureGuard - Perform your gesture", frame)
                cv2.waitKey(1)
            
            time.sleep(0.033)  # ~30 FPS
        
        cv2.destroyAllWindows()
        
        print(f"\nCapture complete: {len(gesture_frames)} frames")
        
        if len(gesture_frames) < 15:  # Reduced threshold
            print(f"❌ Gesture too short: need at least 15 frames, got {len(gesture_frames)}")
            print("\nTips:")
            print("  - Make sure your hand is clearly visible")
            print("  - Start performing gesture immediately after countdown")
            print("  - Keep hand in frame for full 3 seconds")
            return 1
        
        # Flatten all frames into single gesture array
        gesture = np.vstack(gesture_frames)
        
        # Normalize
        from core.detector import normalize_signature
        normalized = normalize_signature(gesture)
        
        print(f"Normalized gesture: {len(normalized)} points")
        
        # Authenticate
        profile, status = auth.authenticate(pin, normalized)
        
        print(f"\nResult: {status}")
        
        if profile:
            print(f"Matched profile: {profile.name}")
            
            if profile.actions:
                print("\nExecuting actions...")
                executor = ActionExecutor()
                results = executor.execute_actions(profile.actions)
                
                for r in results:
                    print(f"  {r}")
        else:
            print("Authentication failed")
            
    finally:
        camera.stop()
        cv2.destroyAllWindows()
    
    return 0


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="GestureGuard - Gesture-Authenticated Environment Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Start in watch mode
  python main.py --record           # Record new gesture
  python main.py --create-profile  # Create new profile
  python main.py --list-profiles   # List profiles
  python main.py --test            # Test authentication
        """
    )
    
    parser.add_argument(
        "-c", "--camera",
        type=int,
        default=0,
        help="Camera index (default: 0)"
    )
    
    # Watch mode (default)
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Start in continuous watch mode"
    )
    
    # Record gesture
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record new gesture samples"
    )
    
    # Create profile
    parser.add_argument(
        "--create-profile",
        action="store_true",
        help="Create a new profile"
    )
    
    # List profiles
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List all profiles"
    )
    
    # Test authentication
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test authentication flow"
    )
    
    args = parser.parse_args()
    
    print_banner()
    
    # Default to watch mode if no command
    if args.watch or not any([args.record, args.create_profile, args.list_profiles, args.test]):
        return start_watch_mode(args)
    elif args.record:
        return record_gesture(args)
    elif args.create_profile:
        return create_profile(args)
    elif args.list_profiles:
        return list_profiles(args)
    elif args.test:
        return test_auth(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
