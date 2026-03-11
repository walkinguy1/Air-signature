"""
GestureGuard - Authenticator Module
Handles DTW-based gesture matching and profile authentication
FR-2.4: Match live gesture against all stored profiles using DTW algorithm
"""

import json
import hashlib
import os
import time
import uuid
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
import numpy as np

# DTW imports
try:
    from dtaidistance import dtw
    from dtaidistance import dtw_ndim
    DTW_AVAILABLE = True
except ImportError:
    # Fallback to simple Euclidean distance if DTW not available
    DTW_AVAILABLE = False
    print("Warning: dtaidistance not installed. Using fallback matching.")


# Configuration
PROFILES_DIR = Path("profiles")
MIN_SIGNATURE_POINTS = 30  # Minimum frames for valid signature
DEFAULT_DTW_THRESHOLD = 0.15  # Normalized DTW distance threshold
MIN_PROFILE_DISTANCE = 0.05  # Minimum DTW distance between different profiles


class Profile:
    """
    User profile containing authentication credentials and actions.
    FR-3.1: Each profile SHALL contain: name, PIN hash, signature data, action sequence
    """
    
    def __init__(
        self,
        profile_id: str,
        name: str,
        pin_hash: str,
        signature_samples: List[List[List[float]]],
        signature_template: Optional[List[List[float]]] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        created_at: Optional[str] = None,
        last_used: Optional[str] = None,
        dtw_threshold: float = DEFAULT_DTW_THRESHOLD
    ):
        self.profile_id = profile_id or str(uuid.uuid4())
        self.name = name
        self.pin_hash = pin_hash
        self.signature_samples = signature_samples
        self.signature_template = signature_template
        self.actions = actions or []
        self.created_at = created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.last_used = last_used
        self.dtw_threshold = dtw_threshold
        
        # Generate template from samples if not provided
        if not self.signature_template and signature_samples:
            self.signature_template = self._generate_template()
    
    def _generate_template(self) -> List[List[float]]:
        """Generate averaged signature template from samples"""
        if not self.signature_samples:
            return []
        
        # Convert to numpy for easier manipulation
        samples = [np.array(s) for s in self.signature_samples]
        
        # Find minimum length
        min_len = min(len(s) for s in samples)
        
        if min_len == 0:
            return []
        
        # Resample all to minimum length using linear interpolation
        resampled = []
        for sample in samples:
            if len(sample) == min_len:
                resampled.append(sample)
            else:
                # Linear interpolation
                x = np.linspace(0, len(sample) - 1, min_len)
                interp = np.array([np.interp(x, np.arange(len(sample)), sample[:, i]) for i in range(sample.shape[1])]).T
                resampled.append(interp)
        
        # Average all samples
        template = np.mean(resampled, axis=0)
        
        return template.tolist()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert profile to dictionary for JSON serialization"""
        return {
            "profile_id": self.profile_id,
            "profile_name": self.name,
            "pin_hash": self.pin_hash,
            "signature_samples": self.signature_samples,
            "signature_template": self.signature_template,
            "actions": self.actions,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "dtw_threshold": self.dtw_threshold
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Profile":
        """Create profile from dictionary"""
        return cls(
            profile_id=data.get("profile_id"),
            name=data.get("profile_name", "Unnamed"),
            pin_hash=data.get("pin_hash", ""),
            signature_samples=data.get("signature_samples", []),
            signature_template=data.get("signature_template"),
            actions=data.get("actions", []),
            created_at=data.get("created_at"),
            last_used=data.get("last_used"),
            dtw_threshold=data.get("dtw_threshold", DEFAULT_DTW_THRESHOLD)
        )
    
    def save(self, profiles_dir: Path = PROFILES_DIR) -> Path:
        """Save profile to JSON file"""
        profiles_dir.mkdir(parents=True, exist_ok=True)
        filepath = profiles_dir / f"{self.profile_id}.json"
        
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        
        return filepath
    
    @classmethod
    def load(cls, profile_id: str, profiles_dir: Path = PROFILES_DIR) -> Optional["Profile"]:
        """Load profile from JSON file"""
        filepath = profiles_dir / f"{profile_id}.json"
        
        if not filepath.exists():
            return None
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        return cls.from_dict(data)
    
    @classmethod
    def load_all(cls, profiles_dir: Path = PROFILES_DIR) -> List["Profile"]:
        """Load all profiles from directory"""
        profiles = []
        
        if not profiles_dir.exists():
            return profiles
        
        for filepath in profiles_dir.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                profiles.append(cls.from_dict(data))
            except Exception as e:
                print(f"Error loading profile {filepath}: {e}")
        
        return profiles
    
    @classmethod
    def delete(cls, profile_id: str, profiles_dir: Path = PROFILES_DIR) -> bool:
        """Delete profile from disk"""
        filepath = profiles_dir / f"{profile_id}.json"
        
        if filepath.exists():
            filepath.unlink()
            return True
        return False


class Authenticator:
    """
    Handles gesture authentication using DTW matching.
    FR-2.4: Match live gesture against all stored profiles using DTW algorithm
    FR-2.5: Execute matched profile action only if BOTH PIN and signature are correct
    """
    
    def __init__(self, profiles_dir: Path = PROFILES_DIR):
        self.profiles_dir = profiles_dir
        self.profiles: List[Profile] = []
        self.failed_attempts = 0
        self.max_failed_attempts = 3  # FR-2.6
        self.is_locked = False
        
        # Load existing profiles
        self.reload_profiles()
    
    def reload_profiles(self) -> None:
        """Reload all profiles from disk"""
        self.profiles = Profile.load_all(self.profiles_dir)
        print(f"Loaded {len(self.profiles)} profiles")
    
    @staticmethod
    def hash_pin(pin: str, salt: str = "") -> str:
        """
        Hash PIN using SHA-256.
        FR-2.1: PINs SHALL be hashed using SHA-256 + salt
        """
        combined = f"{pin}{salt}".encode('utf-8')
        return hashlib.sha256(combined).hexdigest()
    
    def verify_pin(self, pin: str, profile: Profile) -> bool:
        """
        Verify PIN against profile's stored hash.
        
        Args:
            pin: PIN entered by user
            profile: Profile to verify against
            
        Returns:
            True if PIN matches
        """
        # Simple hash without salt for Gold (add salt for Platinum)
        input_hash = self.hash_pin(pin)
        return input_hash == profile.pin_hash
    
    def compute_dtw_distance(self, gesture1: np.ndarray, gesture2: np.ndarray) -> float:
        """
        Compute DTW distance between two gestures.
        
        Args:
            gesture1: First gesture array (N, 3)
            gesture2: Second gesture array (M, 3)
            
        Returns:
            Normalized DTW distance
        """
        if len(gesture1) < 2 or len(gesture2) < 2:
            return float('inf')
        
        if DTW_AVAILABLE:
            try:
                # Use multi-dimensional DTW for 3D coordinates
                distance = dtw_ndim.distance(gesture1.astype(np.float64), 
                                             gesture2.astype(np.float64))
                
                # Normalize by average length
                avg_len = (len(gesture1) + len(gesture2)) / 2
                normalized = distance / avg_len
                
                return normalized
            except Exception as e:
                print(f"DTW error: {e}")
        
        # Fallback: simple Euclidean distance
        return self._fallback_distance(gesture1, gesture2)
    
    def _fallback_distance(self, gesture1: np.ndarray, gesture2: np.ndarray) -> float:
        """Fallback matching using average point-to-point distance"""
        # Resample to same length
        n = min(len(gesture1), len(gesture2), 50)
        if n < 2:
            return float('inf')
        
        g1 = gesture1[np.linspace(0, len(gesture1)-1, n, dtype=int)]
        g2 = gesture2[np.linspace(0, len(gesture2)-1, n, dtype=int)]
        
        distances = np.linalg.norm(g1 - g2, axis=1)
        return np.mean(distances)
    
    def verify_gesture(self, live_gesture: np.ndarray, profile: Profile) -> Tuple[bool, float]:
        """
        Verify live gesture against profile's stored template.
        
        Args:
            live_gesture: Current gesture from camera (N, 3)
            profile: Profile to verify against
            
        Returns:
            Tuple of (is_valid, distance_score)
        """
        if not profile.signature_template:
            return False, float('inf')
        
        template = np.array(profile.signature_template)
        
        # Compute DTW distance
        distance = self.compute_dtw_distance(live_gesture, template)
        
        # Check if within threshold
        is_valid = distance <= profile.dtw_threshold
        
        return is_valid, distance
    
    def authenticate(
        self, 
        pin: str, 
        gesture: np.ndarray
    ) -> Tuple[Optional[Profile], str]:
        """
        Authenticate user with PIN and gesture.
        FR-2.5: Execute matched profile action only if BOTH PIN and signature are correct
        
        Args:
            pin: User's PIN
            gesture: Live gesture from camera
            
        Returns:
            Tuple of (matched_profile or None, status_message)
        """
        if self.is_locked:
            return None, "System locked due to too many failed attempts"
        
        # Validate gesture has enough points
        if len(gesture) < MIN_SIGNATURE_POINTS:
            return None, f"Gesture too short ({len(gesture)} points, need {MIN_SIGNATURE_POINTS})"
        
        # Try to match against all profiles
        best_match = None
        best_distance = float('inf')
        
        for profile in self.profiles:
            # First verify PIN (faster than DTW)
            if not self.verify_pin(pin, profile):
                continue
            
            # Then verify gesture with DTW
            is_valid, distance = self.verify_gesture(gesture, profile)
            
            if is_valid and distance < best_distance:
                best_match = profile
                best_distance = distance
        
        if best_match:
            # Update last used timestamp
            best_match.last_used = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            best_match.save(self.profiles_dir)
            
            self.failed_attempts = 0
            return best_match, "Authentication successful"
        
        # Failed authentication
        self.failed_attempts += 1
        status = f"Authentication failed (attempt {self.failed_attempts}/{self.max_failed_attempts})"
        
        if self.failed_attempts >= self.max_failed_attempts:
            self.is_locked = True
            status = "System locked - too many failed attempts"
        
        return None, status
    
    def get_matching_profile(self, gesture: np.ndarray, threshold_multiplier: float = 1.5) -> List[Tuple[Profile, float]]:
        """
        Get all profiles that could match a gesture (for testing/calibration).
        
        Args:
            gesture: Gesture to match
            threshold_multiplier: Multiply profile thresholds for loose matching
            
        Returns:
            List of (profile, distance) sorted by distance
        """
        matches = []
        
        for profile in self.profiles:
            if not profile.signature_template:
                continue
            
            _, distance = self.verify_gesture(gesture, profile)
            
            if distance <= profile.dtw_threshold * threshold_multiplier:
                matches.append((profile, distance))
        
        # Sort by distance
        matches.sort(key=lambda x: x[1])
        return matches
    
    def create_profile(
        self,
        name: str,
        pin: str,
        signature_samples: List[List[List[float]]],
        actions: Optional[List[Dict[str, Any]]] = None,
        dtw_threshold: float = DEFAULT_DTW_THRESHOLD
    ) -> Profile:
        """
        Create a new profile.
        
        Args:
            name: Profile name
            pin: User's PIN (will be hashed)
            signature_samples: List of gesture samples
            actions: List of actions to execute
            dtw_threshold: Custom DTW threshold
            
        Returns:
            Created profile
        """
        pin_hash = self.hash_pin(pin)
        
        profile = Profile(
            profile_id=str(uuid.uuid4()),
            name=name,
            pin_hash=pin_hash,
            signature_samples=signature_samples,
            actions=actions,
            dtw_threshold=dtw_threshold
        )
        
        profile.save(self.profiles_dir)
        self.reload_profiles()
        
        return profile
    
    def check_profile_distinctness(self, new_samples: List[List[List[float]]]) -> Tuple[bool, str]:
        """
        Check if new samples are sufficiently different from existing profiles.
        FR-3.3: System SHALL validate profile actions at creation time
        
        Args:
            new_samples: New gesture samples to check
            
        Returns:
            Tuple of (is_distinct, message)
        """
        if not self.profiles:
            return True, "First profile - no comparison needed"
        
        new_template = np.array(new_samples[0]) if new_samples else None
        if new_template is None:
            return False, "No samples provided"
        
        for profile in self.profiles:
            if not profile.signature_template:
                continue
            
            template = np.array(profile.signature_template)
            distance = self.compute_dtw_distance(new_template, template)
            
            if distance < MIN_PROFILE_DISTANCE:
                return False, f"Too similar to profile '{profile.name}' (distance: {distance:.3f})"
        
        return True, "Profiles are sufficiently distinct"


# Schema for profile validation
PROFILE_SCHEMA = {
    "profile_id": "string (UUID)",
    "profile_name": "string",
    "pin_hash": "string (SHA-256 hex)",
    "signature_samples": "array of 3D coordinate arrays",
    "signature_template": "array of normalized 3D coordinates",
    "actions": "array of action objects",
    "created_at": "ISO 8601 timestamp",
    "last_used": "ISO 8601 timestamp"
}


if __name__ == "__main__":
    # Test basic functionality
    print("Testing Authenticator...")
    
    # Create test profile
    auth = Authenticator()
    
    # Create a simple test profile
    test_samples = [
        [[i*0.1, i*0.05, i*0.01] for i in range(50)],
        [[i*0.1, i*0.05, i*0.01] for i in range(45)],
    ]
    
    profile = auth.create_profile(
        name="Test Profile",
        pin="1234",
        signature_samples=test_samples,
        actions=[{"type": "hotkey", "keys": ["win", "d"]}]
    )
    
    print(f"Created profile: {profile.profile_id}")
    print(f"Template length: {len(profile.signature_template)}")
    
    # Test authentication
    test_gesture = np.array([[i*0.1, i*0.05, i*0.01] for i in range(50)])
    
    matched, status = auth.authenticate("1234", test_gesture)
    print(f"Auth result: {status}")
    
    # Test wrong PIN
    matched, status = auth.authenticate("0000", test_gesture)
    print(f"Wrong PIN result: {status}")
