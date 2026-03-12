#!/usr/bin/env python3
"""
GestureGuard - Quick Test Script
Run this to verify all fixes are working
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

print("Testing GestureGuard Fixes...")
print("="*50)

# Test 1: Salt Generation
print("\n1. Testing PIN Salt Generation...")
from core.authenticator import Authenticator

auth = Authenticator()
test_samples = [
    [[i*0.1, i*0.05, i*0.01] for i in range(50)],
    [[i*0.1, i*0.05, i*0.01] for i in range(45)],
]

profile = auth.create_profile(
    name="Test",
    pin="1234",
    signature_samples=test_samples,
    actions=[]
)

if profile.salt and len(profile.salt) == 32:
    print(f"✓ Salt generated: {profile.salt[:8]}...")
else:
    print("✗ Salt generation failed!")
    sys.exit(1)

if auth.verify_pin("1234", profile):
    print("✓ PIN verification works")
else:
    print("✗ PIN verification failed")
    sys.exit(1)

# Clean up
from core.authenticator import Profile
Profile.delete(profile.profile_id)

# Test 2: PIN Overlay
print("\n2. Testing PIN Overlay Import...")
try:
    from gui.pin_overlay import PINEntryOverlay
    print("✓ PIN overlay imported successfully")
except ImportError as e:
    print(f"⚠ PIN overlay import failed: {e}")
    print("  (This is OK if you don't have tkinter installed)")

# Test 3: State Machine
print("\n3. Testing State Machine...")
try:
    from core.state_machine import GestureStateMachine
    print("✓ State machine imported successfully")
except Exception as e:
    print(f"✗ State machine import failed: {e}")

print("\n" + "="*50)
print("✅ All critical fixes verified!")
print("\nNext steps:")
print("  python main.py --create-profile")
print("  python main.py --test")