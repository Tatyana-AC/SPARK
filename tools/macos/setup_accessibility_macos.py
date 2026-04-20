"""
macOS Accessibility - Easy Setup Helper

This script helps you properly add Python to macOS Accessibility permissions.
"""

import os
import sys
import subprocess
import json

def get_python_info():
    """Get Python executable information."""
    print("\n" + "=" * 70)
    print("PYTHON EXECUTABLE INFO")
    print("=" * 70)
    
    python_path = sys.executable
    print(f"\nPython Executable Path:")
    print(f"  {python_path}\n")
    
    print("How to use this:")
    print("  1. In System Settings → Privacy & Security → Accessibility")
    print("  2. Click the lock icon 🔒 and enter your password")
    print("  3. Click the '+' button")
    print("  4. Press Cmd+Shift+G (Go to folder)")
    print("  5. Paste this path:")
    print(f"     {python_path}")
    print("  6. Press Enter, then click 'Open'")
    print("  7. Restart your application\n")
    
    # Copy to clipboard
    try:
        process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
        process.communicate(python_path.encode('utf-8'))
        print("✓ Path copied to clipboard! (Cmd+V to paste in System Settings)\n")
    except Exception as e:
        print(f"Could not copy to clipboard: {e}\n")
    
    return python_path


def check_accessibility_permission():
    """Check if accessibility permissions are already granted."""
    print("=" * 70)
    print("CHECKING ACCESSIBILITY PERMISSIONS")
    print("=" * 70 + "\n")
    
    try:
        # Try to use the PyObjC accessibility API
        try:
            import Quartz
            trusted = Quartz.AXIsProcessTrusted()
            
            if trusted:
                print("✓ ACCESSIBILITY PERMISSIONS ALREADY GRANTED!")
                print("  The application has accessibility permissions.\n")
                return True
            else:
                print("✗ ACCESSIBILITY PERMISSIONS NOT GRANTED")
                print("  The application needs to be added to:")
                print("  System Settings → Privacy & Security → Accessibility\n")
                return False
        except ImportError:
            print("⚠ PyObjC not installed")
            print("  Install with: pip install pyobjc-framework-Cocoa\n")
            return None
    
    except Exception as e:
        print(f"⚠ Could not check permissions: {e}\n")
        return None


def open_accessibility_settings():
    """Open System Settings to Accessibility pane."""
    print("=" * 70)
    print("OPENING SYSTEM SETTINGS")
    print("=" * 70 + "\n")
    
    print("Attempting to open System Settings...\n")
    
    methods = [
        ("URL Scheme", ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"]),
        ("System Settings App", ["open", "-a", "System Settings"]),
        ("Preferences", ["open", "-a", "System Preferences"]),
    ]
    
    for method_name, cmd in methods:
        try:
            print(f"Trying: {method_name}...")
            subprocess.run(cmd, check=True, timeout=5)
            print(f"✓ Opened using: {method_name}\n")
            return True
        except Exception as e:
            print(f"  ✗ {method_name} failed: {e}")
            continue
    
    print("\n✗ Could not automatically open System Settings")
    print("  Please manually open:")
    print("  Apple menu → System Settings")
    print("  → Privacy & Security → Accessibility\n")
    return False


def manual_instructions():
    """Print detailed manual instructions."""
    print("=" * 70)
    print("MANUAL SETUP INSTRUCTIONS")
    print("=" * 70)
    
    print("""
Follow these steps to manually add Python to Accessibility:

1. CLOSE This Script ← Important!

2. Open System Settings
   (Apple menu → System Settings)

3. In the sidebar, find: Privacy & Security
   (You may need to scroll down)

4. Find: Accessibility
   (Scroll down if you don't see it immediately)

5. At the bottom-left, you'll see a 🔒 LOCK ICON
   Click it and enter your password

6. Now you should see a '+' button below a list of apps
   Click the '+' button

7. A file picker will open
   - Press Cmd+Shift+G (Go to folder)
   - A text field will appear
   - Paste your Python path:
   
   """ + sys.executable + """
   
   - Press Enter
   - Click "Open"

8. You should see Python added to the list with a ✓ checkmark

9. CLOSE System Settings

10. RESTART this script or your application

═══════════════════════════════════════════════════════════════════════

STILL NOT WORKING?

Try this alternative method:
  1. In System Settings > Accessibility
  2. Click the '+' button (don't use Cmd+Shift+G)
  3. Navigate to Applications → Utilities → Terminal
  4. Click "Open"

This gives your entire Terminal app access, which will make Python work.

═══════════════════════════════════════════════════════════════════════
""")


def show_venv_info():
    """Show information about virtual environment."""
    print("=" * 70)
    print("VIRTUAL ENVIRONMENT INFO")
    print("=" * 70 + "\n")
    
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("✓ Running in VIRTUAL ENVIRONMENT")
        print(f"  venv location: {sys.prefix}")
        print(f"  Python exe: {sys.executable}\n")
        print("  Make sure to add THIS Python executable above!")
        print(f"  Path: {sys.executable}\n")
    else:
        print("✓ Running system Python")
        print(f"  Python exe: {sys.executable}\n")


def interactive_menu():
    """Show interactive menu."""
    while True:
        print("\n" + "=" * 70)
        print("ACCESSIBILITY PERMISSIONS HELPER")
        print("=" * 70)
        print("\nWhat would you like to do?\n")
        print("1. Check current permission status")
        print("2. Get Python executable path (to add manually)")
        print("3. Open System Settings (automatic)")
        print("4. Show manual setup instructions")
        print("5. Show my Python/venv info")
        print("6. Exit\n")
        
        choice = input("Choose an option (1-6): ").strip()
        
        if choice == '1':
            check_accessibility_permission()
            input("\nPress Enter to continue...")
        elif choice == '2':
            get_python_info()
            input("Press Enter to continue...")
        elif choice == '3':
            open_accessibility_settings()
            input("Press Enter after granting permissions...")
            check_accessibility_permission()
            input("\nPress Enter to continue...")
        elif choice == '4':
            manual_instructions()
            input("\nPress Enter to continue...")
        elif choice == '5':
            show_venv_info()
            print("=" * 70)
            get_python_info()
            input("Press Enter to continue...")
        elif choice == '6':
            print("\nGoodbye! Remember to grant accessibility permissions.\n")
            break
        else:
            print("Invalid choice. Please try again.")


def main():
    """Main function."""
    print("\n" + "=" * 70)
    print("macOS Accessibility Permissions - Setup Helper")
    print("=" * 70)
    
    # Check if running on macOS
    if sys.platform != 'darwin':
        print("\n✗ This script is for macOS only!")
        print(f"  You're running: {sys.platform}\n")
        return
    
    # Show Python info first
    print("\nYour Python Information:")
    print("-" * 70)
    show_venv_info()
    get_python_info()
    
    # Check current permissions
    print()
    check_accessibility_permission()
    
    # Interactive menu
    interactive_menu()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExiting...\n")
