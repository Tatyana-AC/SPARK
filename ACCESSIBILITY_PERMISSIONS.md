# Accessibility Permissions Guide for macOS

## Quick Answer

On macOS, you **must manually grant permissions** in System Settings. There's no programmatic way to do this automatically due to security restrictions.

## How to Grant Permissions (3 steps)

### Step 1: Open System Settings
```
Apple menu → System Settings
```

### Step 2: Navigate to Accessibility
```
Privacy & Security → Accessibility (scroll down to find it)
```

### Step 3: Add Your Application
1. Click the **lock icon 🔒** at the bottom-left
2. Enter your **password** when prompted
3. Click the **'+'** button
4. Select your Python executable or application:
   - For direct Python: `/usr/bin/python3`
   - For your IDE: VS Code, PyCharm, etc.
   - For this project: add the Python executable you use to launch `spark_app_v2.py`
5. Click **'Open'** to add it
6. You should see a **✓** checkmark next to the app

### Step 4: Restart
Restart your application or script for changes to take effect.

## Finding Your Python Executable

If you're not sure which Python to add:

```python
import sys
print(sys.executable)
```

Run this and copy the output path, then use **Cmd+Shift+G** in System Settings to paste it.

## Visual Guide

**In System Settings:**
```
Privacy & Security
  ↓
Accessibility
  ↓
[🔒 Lock] [+] [-]
  ↓
(Click lock, enter password)
  ↓
(Click +, find your app)
  ↓
[✓] Your Application
```

## For Different Environments

### VS Code
1. Add `/usr/bin/python3` to Accessibility
2. Also add VS Code itself if needed

### PyCharm
Just add PyCharm to Accessibility

### Terminal
No special permissions needed - Terminal already has access

### Jupyter / Anaconda
Add the Python executable from your conda environment:
```bash
which python3  # Find the path
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Still getting permission error after adding | Restart your app completely, try again |
| Can't find the app in file picker | Close the app, then try adding it again |
| Doesn't appear in the Accessibility list | Make sure you clicked the lock and entered password |
| Not sure which Python to add | Run `import sys; print(sys.executable)` in Python |

## Security Note

✓ These permissions are **safe** - they only read text from other apps  
✓ The app **cannot** control your mouse or keyboard  
✓ The app **cannot** modify other applications  
✓ You can **revoke permissions** anytime in System Settings

## After Setup

Once permissions are granted, you can use the accessibility module:

```python
from host_pc.accessibility import AccessibilityManager

manager = AccessibilityManager()

# Check if ready
if manager.check_permissions():
    context = manager.get_context(method='auto')
    if context:
        print(f"App: {context.window_info.app_name}")
        print(f"Text: {context.text}")
```

## Need More Help?

1. Run the demo with debug logging:
   ```bash
   python spark_app_v2.py
   ```

2. Check logs for specific errors

3. Verify permissions are granted in System Settings

4. Try adding the exact executable path with **Cmd+Shift+G**

---

**That's it!** Once permissions are granted, the accessibility module works smoothly. 🎉
