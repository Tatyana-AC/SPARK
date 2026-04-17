# SPARK System Diagram

This is the current high-level architecture for the active branch.

```mermaid
flowchart LR
    subgraph Host["Host PC (macOS / Windows)"]
        UI["spark_app_v2.py\nPyQt panel"]
        AX["AccessibilityManager\nwindow + text extraction"]
        Browser["browser.py + browser_windows.py\ntab title + URL metadata"]
        Web["web_content.py + web_content_windows.py\nlive tab text + HTTP/UIA heuristics"]
        Tracker["WindowContextTracker\nin-memory history + QSettings"]
        Live["LiveCaptureFeed\nRELEASE OUTPUT"]
        Hotkeys["GlobalHotkeyManager"]
        HID["SparkHIDClient\nRaw HID upload"]
        CDC["SerialSender\nCDC packets"]
        DBView["JetsonDbViewerDialog\nread-only snapshot browser"]
        Snap["jetson_db_snapshot.py\nvalidated snapshot + paging"]
    end

    subgraph Pico["Pico Hub (CircuitPython)"]
        Boot["boot.py\nUSB identity + interfaces"]
        Code["code.py\nCDC relay + summarize transport + HID handler"]
        Upload["upload_protocol.py"]
        Bridge["serial_bridge.py"]
    end

    subgraph Jetson["Jetson Brain"]
        Receiver["jetson/pico_llm_bridge.py\nUART broker + PacketParser"]
        JDB["JetsonDB\nrich sessions + button_events"]
        LLM["llama.cpp server\nOpenAI-compatible API"]
    end

    AX --> UI
    Browser --> UI
    Web --> UI
    UI --> Tracker
    UI --> Live
    Hotkeys --> UI
    UI --> HID
    UI --> CDC
    UI --> DBView
    DBView --> Snap

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
- Browser-aware polling on Windows now combines browser metadata, live UIA extraction, and HTTP fallback before it accepts raw accessibility fallback text.
- `View Jetson DB` uses a temporary validated snapshot copy so the UI can inspect Jetson tables without holding the live database open.
- The Pico acknowledges text uploads but does not type text back into the focused external app in the active runtime.
- The active `spark_app_v2.py` runtime does not use a host-local SQLite database. Jetson is the durable state owner for captured context.
- `pico_reference/main.py` remains a readable reference, but the deployed firmware entrypoints are `pico/boot.py` and `pico/code.py`.
