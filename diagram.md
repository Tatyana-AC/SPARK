graph TD
    %% Define Styles
    classDef laptop fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
    classDef jetson fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef hardware fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef database fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;

    %% Zone 1: The User's Laptop
    subgraph Zone 1: User's Laptop (The Host)
        App[Active Application <br> Chrome, Word, Slack]
        Manager[Accessibility Manager <br> manager.py]
        WinProv[Windows/Mac Provider <br> windows_provider.py]
        Paste[Clipboard Injector <br> pyautogui / pyperclip]
    end

    %% Zone 2: The Data Layer
    subgraph Zone 2: The Memory Bank
        DB[(spark.db <br> SQLite FTS5)]
        VectorDB[(ChromaDB <br> Vectors - Optional)]
    end

    %% Zone 3: The Jetson AGX
    subgraph Zone 3: Jetson AGX (The Brain)
        StateClass[State Classifier <br> Study/Write/Respond]
        LLM[Local LLM <br> Llama-3 8B]
        API[Jetson API Server]
    end

    %% Zone 4: The Physical Device
    subgraph Zone 4: Spark Hardware
        Screen[OLED Display <br> Shows 4 Options]
        Keys[4 Dynamic Soft Keys]
        Release[Physical 'Release' Button]
    end

    %% --- Connections ---

    %% Data Ingestion (The "Eyes")
    App -- OS API calls --> WinProv
    WinProv -- "Extracts Text" --> Manager
    Manager -- "Writes Window State" --> DB

    %% Context Reading
    DB -- "Reads Active App & History" --> StateClass
    StateClass -- "Updates Button Labels" --> API
    API -- "Sends Display Data" --> Screen

    %% User Interaction
    Keys -- "User Selects Option" --> API
    API -- "Fetches Context" --> DB
    API -- "Prompts AI" --> LLM

    %% Action Execution (The "Hands")
    LLM -- "Generates Draft/Summary" --> Release
    Release -- "User Confirms Action" --> Manager
    Manager -- "Triggers paste_text()" --> Paste
    Paste -- "Ctrl+V" --> App

    %% Apply Styles
    class App,Manager,WinProv,Paste laptop;
    class DB,VectorDB database;
    class StateClass,LLM,API jetson;
    class Screen,Keys,Release hardware;