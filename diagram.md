# SPARK System Diagram

This is the current high-level architecture for the active branch.

```mermaid
flowchart LR
    subgraph Host["Host PC (macOS / Windows)"]
        UI["spark_app_v2.py\nPyQt panel"]
        AX["AccessibilityManager\nwindow + text extraction"]
        Tracker["WindowContextTracker\nin-memory history + QSettings"]
        Live["LiveCaptureFeed\nRELEASE OUTPUT"]
        Hotkeys["GlobalHotkeyManager"]
        HID["SparkHIDClient\nRaw HID upload"]
        CDC["SerialSender\nCDC packets"]
    end

    subgraph Pico["Pico Hub (CircuitPython)"]
        Boot["boot.py\nUSB identity + interfaces"]
        Code["code.py\nCDC relay + button scan + HID handler"]
        Upload["upload_protocol.py"]
        Bridge["serial_bridge.py"]
    end

    subgraph Jetson["Jetson Brain"]
        Receiver["jetson/pico_llm_bridge.py\nUART broker + PacketParser"]
        JDB["JetsonDB\nrich sessions + button_events"]
        LLM["llama.cpp server\nOpenAI-compatible API"]
    end

    AX --> UI
    UI --> Tracker
    UI --> Live
    Hotkeys --> UI
    UI --> HID
    UI --> CDC

    HID --> Upload
    CDC --> Bridge
    Boot --> Code
    Upload --> Code
    Bridge --> Code

    Bridge --> Receiver
    Code --> Receiver
    Receiver --> JDB
    Receiver --> LLM
```

## Notes

- The host has two independent device paths:
  - Raw HID for `Release Text` uploads and device status.
  - USB CDC serial for `CONTEXT_NEW` / `CONTEXT_UPDATE` and direct framed summarize packets heading toward the Jetson.
- The Pico acknowledges text uploads but does not type text back into the focused external app in the active runtime.
- The active `spark_app_v2.py` runtime does not use a host-local SQLite database. Jetson is the durable state owner for captured context.
- `pico/main.py` remains a readable reference, but the deployed firmware entrypoints are `pico/boot.py` and `pico/code.py`.
