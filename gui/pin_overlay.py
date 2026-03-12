"""
GestureGuard - PIN Entry Overlay
Transparent overlay window for secure PIN entry during authentication
FR-2.2: System SHALL display PIN entry overlay within 500ms of trigger
FR-2.3: PIN entry SHALL timeout after 10 seconds of inactivity
"""

import tkinter as tk
from tkinter import ttk
import time
from typing import Optional, Callable
import threading


class PINEntryOverlay:
    """
    Transparent overlay window for PIN entry during authentication.
    
    Features:
    - Always-on-top transparent window
    - Masked PIN entry (shows ••••)
    - Countdown timer with visual feedback
    - Keyboard shortcuts (Enter to submit, Esc to cancel)
    - Auto-dismiss on timeout
    """
    
    def __init__(
        self,
        timeout: float = 10.0,
        on_submit: Optional[Callable[[str], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        on_timeout: Optional[Callable[[], None]] = None
    ):
        """
        Initialize PIN entry overlay.
        
        Args:
            timeout: Seconds before auto-dismiss (default: 10.0)
            on_submit: Callback when PIN is submitted (receives PIN string)
            on_cancel: Callback when user cancels (ESC key)
            on_timeout: Callback when timeout occurs
        """
        self.timeout = timeout
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.on_timeout = on_timeout
        
        # State
        self.pin = ""
        self.is_submitted = False
        self.is_cancelled = False
        self.start_time = None
        
        # UI components
        self.root = None
        self.pin_label = None
        self.timer_label = None
        self.status_label = None
        
    def show(self) -> Optional[str]:
        """
        Display the PIN entry overlay and wait for input.
        
        Returns:
            Entered PIN string, or None if cancelled/timeout
        """
        self._create_window()
        self.start_time = time.time()
        
        # Start timer thread
        timer_thread = threading.Thread(target=self._update_timer, daemon=True)
        timer_thread.start()
        
        # Run main loop (blocks until window closed)
        self.root.mainloop()
        
        # Return result
        if self.is_submitted:
            return self.pin
        return None
    
    def _create_window(self):
        """Create the overlay window with all UI elements"""
        self.root = tk.Tk()
        self.root.title("GestureGuard - Authentication")
        
        # Window configuration
        self.root.attributes('-topmost', True)  # Always on top
        self.root.attributes('-alpha', 0.95)    # Slightly transparent
        self.root.overrideredirect(False)       # Keep window decorations for now
        
        # Window size and position (center of screen)
        window_width = 400
        window_height = 250
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Styling
        self.root.configure(bg="#2c3e50")
        
        # Main frame
        main_frame = tk.Frame(self.root, bg="#2c3e50", padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = tk.Label(
            main_frame,
            text="🔐 Authentication Required",
            font=("Helvetica", 18, "bold"),
            bg="#2c3e50",
            fg="#ecf0f1"
        )
        title_label.pack(pady=(0, 10))
        
        # Instruction
        instruction_label = tk.Label(
            main_frame,
            text="Enter your 4-digit PIN",
            font=("Helvetica", 12),
            bg="#2c3e50",
            fg="#bdc3c7"
        )
        instruction_label.pack(pady=(0, 20))
        
        # PIN display (shows •••• as user types)
        self.pin_label = tk.Label(
            main_frame,
            text="____",
            font=("Courier", 32, "bold"),
            bg="#34495e",
            fg="#ecf0f1",
            width=6,
            relief=tk.RAISED,
            bd=2
        )
        self.pin_label.pack(pady=(0, 20))
        
        # Timer display
        self.timer_label = tk.Label(
            main_frame,
            text=f"Time remaining: {int(self.timeout)}s",
            font=("Helvetica", 11),
            bg="#2c3e50",
            fg="#e74c3c"
        )
        self.timer_label.pack(pady=(0, 10))
        
        # Status message
        self.status_label = tk.Label(
            main_frame,
            text="Press ESC to cancel",
            font=("Helvetica", 9),
            bg="#2c3e50",
            fg="#95a5a6"
        )
        self.status_label.pack()
        
        # Button frame
        button_frame = tk.Frame(main_frame, bg="#2c3e50")
        button_frame.pack(pady=(10, 0))
        
        # Submit button
        submit_btn = tk.Button(
            button_frame,
            text="Submit",
            font=("Helvetica", 11),
            bg="#27ae60",
            fg="white",
            activebackground="#229954",
            activeforeground="white",
            command=self._submit,
            padx=20,
            pady=5,
            relief=tk.FLAT,
            cursor="hand2"
        )
        submit_btn.pack(side=tk.LEFT, padx=5)
        
        # Cancel button
        cancel_btn = tk.Button(
            button_frame,
            text="Cancel",
            font=("Helvetica", 11),
            bg="#e74c3c",
            fg="white",
            activebackground="#c0392b",
            activeforeground="white",
            command=self._cancel,
            padx=20,
            pady=5,
            relief=tk.FLAT,
            cursor="hand2"
        )
        cancel_btn.pack(side=tk.LEFT, padx=5)
        
        # Keyboard bindings
        self.root.bind('<Key>', self._on_key_press)
        self.root.bind('<Return>', lambda e: self._submit())
        self.root.bind('<Escape>', lambda e: self._cancel())
        self.root.bind('<BackSpace>', lambda e: self._backspace())
        
        # Focus window
        self.root.focus_force()
    
    def _on_key_press(self, event):
        """Handle keyboard input"""
        # Only accept digits
        if event.char.isdigit() and len(self.pin) < 4:
            self.pin += event.char
            self._update_pin_display()
            
            # Auto-submit if 4 digits entered
            if len(self.pin) == 4:
                self.root.after(200, self._submit)  # Small delay for visual feedback
    
    def _backspace(self):
        """Remove last digit"""
        if self.pin:
            self.pin = self.pin[:-1]
            self._update_pin_display()
    
    def _update_pin_display(self):
        """Update the PIN display with dots"""
        display = ""
        for i in range(4):
            if i < len(self.pin):
                display += "●"
            else:
                display += "_"
        
        self.pin_label.config(text=display)
        
        # Update status
        if len(self.pin) == 4:
            self.status_label.config(text="Press ENTER or click Submit", fg="#27ae60")
        else:
            remaining = 4 - len(self.pin)
            self.status_label.config(
                text=f"Enter {remaining} more digit{'s' if remaining > 1 else ''}",
                fg="#95a5a6"
            )
    
    def _update_timer(self):
        """Update countdown timer (runs in separate thread)"""
        while True:
            if not self.root or not self.root.winfo_exists():
                break
            
            elapsed = time.time() - self.start_time
            remaining = max(0, self.timeout - elapsed)
            
            if remaining <= 0:
                # Timeout occurred
                self.root.after(0, self._handle_timeout)
                break
            
            # Update timer display
            seconds_left = int(remaining)
            self.root.after(0, lambda: self._set_timer_text(seconds_left))
            
            # Change color when time is running out
            if remaining < 3:
                self.root.after(0, lambda: self.timer_label.config(fg="#e74c3c"))
            elif remaining < 5:
                self.root.after(0, lambda: self.timer_label.config(fg="#f39c12"))
            
            time.sleep(0.1)
    
    def _set_timer_text(self, seconds: int):
        """Update timer label text (called from main thread)"""
        if self.timer_label and self.timer_label.winfo_exists():
            self.timer_label.config(text=f"Time remaining: {seconds}s")
    
    def _submit(self):
        """Handle PIN submission"""
        if len(self.pin) != 4:
            self.status_label.config(
                text="PIN must be 4 digits!",
                fg="#e74c3c"
            )
            return
        
        self.is_submitted = True
        
        # Call callback if provided
        if self.on_submit:
            self.on_submit(self.pin)
        
        # Close window
        self.root.destroy()
    
    def _cancel(self):
        """Handle cancellation"""
        self.is_cancelled = True
        
        # Call callback if provided
        if self.on_cancel:
            self.on_cancel()
        
        # Close window
        self.root.destroy()
    
    def _handle_timeout(self):
        """Handle timeout"""
        if self.root and self.root.winfo_exists():
            # Show timeout message briefly
            self.status_label.config(text="Timeout! Authentication failed.", fg="#e74c3c")
            self.timer_label.config(text="Time's up!", fg="#e74c3c")
            
            # Call callback if provided
            if self.on_timeout:
                self.on_timeout()
            
            # Close after brief delay
            self.root.after(1000, self.root.destroy)


def test_pin_overlay():
    """Test the PIN overlay (standalone execution)"""
    print("Testing PIN Entry Overlay...")
    print("="*50)
    
    def on_submit(pin):
        print(f"✓ PIN submitted: {pin}")
    
    def on_cancel():
        print("✗ Authentication cancelled")
    
    def on_timeout():
        print("⏱ Authentication timeout")
    
    overlay = PINEntryOverlay(
        timeout=15.0,
        on_submit=on_submit,
        on_cancel=on_cancel,
        on_timeout=on_timeout
    )
    
    result = overlay.show()
    
    print("\n" + "="*50)
    if result:
        print(f"Result: PIN entered = {result}")
    else:
        print("Result: No PIN (cancelled or timeout)")


if __name__ == "__main__":
    test_pin_overlay()