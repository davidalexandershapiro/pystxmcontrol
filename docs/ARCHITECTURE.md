# pystxmcontrol Software Architecture

## System Overview

pystxmcontrol is a Python-based control system for Scanning Transmission X-ray Microscopy (STXM) at synchrotron beamlines. The architecture follows a client-server model with modular hardware drivers and flexible scan routines.

## High-Level Architecture Flowchart

```mermaid
flowchart TB
    %% Top Level - User Interfaces
    subgraph UI["User Interface Layer"]
        GUI["GUI (mainwindow.py)<br/>PySide6/PyQtGraph"]
        CLI["Command Line Interface"]
        Scripts["External Scripts"]
    end

    %% Client Layer
    subgraph Client["Client Layer"]
        STXMClient["STXM Client<br/>(stxm.py)"]
        ZMQClient["ZMQ Communication"]
    end

    %% Server Layer
    subgraph Server["Server Layer (server.py)"]
        ZMQServer["ZMQ Command Handler<br/>(Async)"]
        CommandRouter["Command Router<br/>(18+ commands)"]
        OpLogger["Operation Logger<br/>(Command/Motor/Scan Logging)"]
    end

    %% Controller Layer
    subgraph Controller["Controller Layer (controller.py)"]
        MotorCtrl["Motor Controller"]
        DAQCtrl["DAQ Controller"]
        ScanCtrl["Scan Controller"]
        ConfigMgr["Configuration Manager"]
        Monitor["Motor Monitor Thread"]
    end

    %% Data Management
    subgraph Data["Data Management"]
        DataHandler["Data Handler<br/>(dataHandler.py)"]
        DataWriter["Data Writer<br/>(HDF5/NeXus)"]
        DataQueue["Async Data Queue"]
        ZMQPub["ZMQ Publisher<br/>(Live Data Stream)"]
    end

    %% Scan Engine
    subgraph Scans["Scan Engine"]
        BaseScan["BaseScan<br/>(Abstract Base Class)"]
        LineImage["Linear Image Scan"]
        Focus["Focus Scan"]
        Spectrum["Spectrum Scan"]
        Ptycho["Ptychography Scan"]
        CustomScans["Custom Scans..."]
    end

    %% Hardware Drivers
    subgraph Drivers["Hardware Driver Layer"]
        MotorDrivers["Motor Drivers<br/>(Aerotech, XPS, E712, etc.)"]
        DAQDrivers["DAQ Drivers<br/>(Keysight, Xspress3, CCD)"]
        DerivedMotors["Derived Motors<br/>(Energy, Piezo+Stepper)"]
    end

    %% Hardware
    subgraph Hardware["Physical Hardware"]
        Motors["Motors & Stages"]
        Detectors["Detectors & DAQs"]
        Beamline["Beamline Components"]
    end

    %% Database
    subgraph Database["Persistent Storage"]
        SQLite["SQLite Database<br/>(Monthly Rotation)"]
        HDF5["HDF5 Data Files<br/>(NeXus Format)"]
        Config["JSON Config Files"]
    end

    %% Connections - User to Client
    GUI --> STXMClient
    CLI --> STXMClient
    Scripts --> STXMClient

    %% Client to Server
    STXMClient <-->|"ZMQ REQ/REP<br/>(Commands)"| ZMQClient
    ZMQClient <-->|"TCP Port 9999"| ZMQServer

    %% Server Internal
    ZMQServer --> CommandRouter
    CommandRouter --> Controller
    CommandRouter --> OpLogger

    %% Controller Internal
    Controller --> MotorCtrl
    Controller --> DAQCtrl
    Controller --> ScanCtrl
    Controller --> ConfigMgr
    MotorCtrl --> Monitor

    %% Scan Execution
    ScanCtrl --> BaseScan
    BaseScan --> LineImage
    BaseScan --> Focus
    BaseScan --> Spectrum
    BaseScan --> Ptycho
    BaseScan --> CustomScans

    %% Data Flow
    ScanCtrl --> DataHandler
    DAQCtrl --> DataHandler
    DataHandler --> DataQueue
    DataQueue --> DataWriter
    DataQueue --> ZMQPub

    %% Live Data Stream
    ZMQPub -->|"TCP Port 9998<br/>(Live Images)"| GUI

    %% Hardware Abstraction
    MotorCtrl --> MotorDrivers
    MotorCtrl --> DerivedMotors
    DAQCtrl --> DAQDrivers

    %% Hardware Control
    MotorDrivers --> Motors
    DAQDrivers --> Detectors
    DerivedMotors --> Motors

    %% Persistence
    OpLogger --> SQLite
    DataWriter --> HDF5
    ConfigMgr --> Config
    ConfigMgr --> Controller

    %% Styling
    classDef uiClass fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    classDef clientClass fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef serverClass fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef controllerClass fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    classDef dataClass fill:#fce4ec,stroke:#880e4f,stroke-width:2px
    classDef scanClass fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    classDef driverClass fill:#e0f2f1,stroke:#004d40,stroke-width:2px
    classDef hwClass fill:#efebe9,stroke:#3e2723,stroke-width:2px
    classDef dbClass fill:#f1f8e9,stroke:#33691e,stroke-width:2px

    class GUI,CLI,Scripts uiClass
    class STXMClient,ZMQClient clientClass
    class ZMQServer,CommandRouter,OpLogger serverClass
    class MotorCtrl,DAQCtrl,ScanCtrl,ConfigMgr,Monitor controllerClass
    class DataHandler,DataWriter,DataQueue,ZMQPub dataClass
    class BaseScan,LineImage,Focus,Spectrum,Ptycho,CustomScans scanClass
    class MotorDrivers,DAQDrivers,DerivedMotors driverClass
    class Motors,Detectors,Beamline hwClass
    class SQLite,HDF5,Config dbClass
```

## Component Details

### 1. User Interface Layer
- **GUI**: PySide6-based graphical interface with PyQtGraph for real-time visualization
- **CLI**: Command-line interface for scripting and automation
- **Scripts**: External Python scripts using the STXM client API

### 2. Client Layer
- **STXM Client**: High-level API for instrument control
- **ZMQ Communication**: Request/reply pattern for commands, publish/subscribe for data

### 3. Server Layer
- **ZMQ Command Handler**: Asynchronous command processing
- **Command Router**: Routes 18+ command types (moveMotor, scan, getData, etc.)
- **Operation Logger**: Logs all commands, motor moves, and scans to SQLite database

### 4. Controller Layer
- **Motor Controller**: Manages all motor instances and movements
- **DAQ Controller**: Manages data acquisition devices
- **Scan Controller**: Orchestrates scan execution in separate thread
- **Configuration Manager**: Loads and manages motor/scan/DAQ configurations
- **Motor Monitor**: Background thread for position monitoring

### 5. Data Management
- **Data Handler**: Coordinates data collection and storage
- **Data Writer**: Writes HDF5/NeXus formatted data files
- **Async Data Queue**: Decouples data collection from I/O
- **ZMQ Publisher**: Streams live data to GUI for real-time display

### 6. Scan Engine
- **BaseScan**: Abstract base class providing common scan functionality
  - DAQ configuration
  - Motor control
  - Energy handling
  - Timing management
- **Scan Implementations**:
  - Linear image scans
  - Focus scans
  - Spectroscopy scans
  - Ptychography scans
  - Custom user-defined scans

### 7. Hardware Driver Layer
- **Motor Drivers**: Support for multiple motor controllers
  - Aerotech (XY stages)
  - Newport XPS (precision positioning)
  - Physik Instrumente E712 (piezo)
  - EPICS motors
- **DAQ Drivers**: Data acquisition devices
  - Keysight counters/timers
  - Xspress3 fluorescence detector
  - Area detectors (CCD)
- **Derived Motors**: Virtual motors with special behavior
  - Energy motor (monochromator + focus coupling)
  - Piezo+Stepper (extended range positioning)

### 8. Physical Hardware
- **Motors & Stages**: Sample positioning, zone plate, OSA, detectors
- **Detectors**: Counters, fluorescence detectors, CCDs
- **Beamline Components**: Monochromator, shutters, gates

### 9. Persistent Storage
- **SQLite Database**: Operation logging (monthly rotation)
  - Motor positions
  - Motor moves
  - Scans
  - Commands
- **HDF5 Data Files**: Scientific data in NeXus format
- **JSON Config Files**: Motor, scan, and DAQ configurations

## Data Flow Diagrams

### Command Execution Flow

```mermaid
sequenceDiagram
    participant GUI
    participant Client
    participant Server
    participant Controller
    participant Hardware
    participant OpLogger

    GUI->>Client: moveMotor("SampleX", 100.5)
    Client->>Server: ZMQ Command
    Server->>OpLogger: Log Command Start
    Server->>Controller: Execute Move
    Controller->>Hardware: Send Motion Command
    Hardware-->>Controller: Motion Complete
    Controller->>OpLogger: Log Move Success
    Controller-->>Server: Success Response
    Server-->>Client: ZMQ Reply
    Client-->>GUI: Update Display
```

### Scan Execution Flow

```mermaid
sequenceDiagram
    participant GUI
    participant Server
    participant ScanCtrl
    participant ScanImpl
    participant DataHandler
    participant OpLogger
    participant ZMQPub

    GUI->>Server: Start Scan
    Server->>OpLogger: Log Scan Start
    Server->>ScanCtrl: Execute Scan
    ScanCtrl->>ScanImpl: Run Scan Instance

    loop For each line/point
        ScanImpl->>Hardware: Move Motors
        ScanImpl->>Hardware: Acquire Data
        ScanImpl->>DataHandler: Process Data
        DataHandler->>ZMQPub: Publish Live Data
        ZMQPub-->>GUI: Display Image
    end

    ScanImpl->>DataHandler: Save Complete Dataset
    DataHandler->>HDF5: Write NeXus File
    ScanImpl->>OpLogger: Log Scan Complete
    ScanImpl-->>ScanCtrl: Scan Done
    ScanCtrl-->>Server: Success
    Server-->>GUI: Scan Complete
```

### Motor Position Monitoring Flow

```mermaid
flowchart LR
    Monitor["Monitor Thread<br/>(10s period)"] -->|Read Positions| Motors
    Motors -->|Current Positions| Monitor
    Monitor -->|Log Positions| OpLogger
    OpLogger -->|Store| SQLite
    SQLite -->|Query| PlotTools["Plotting Tools"]
    PlotTools -->|Visualize| User
```

## Key Design Patterns

### 1. Client-Server Architecture
- **Separation**: GUI and control logic are separate processes
- **Communication**: ZMQ for efficient inter-process communication
- **Scalability**: Multiple clients can connect to one server

### 2. Abstract Base Class Pattern (BaseScan)
- **Common functionality**: Shared across all scan types
- **Extensibility**: Easy to add new scan types
- **Code reuse**: Reduces duplication

### 3. Async Queue Pattern
- **Non-blocking**: Motor moves don't wait for logging
- **Decoupling**: Data collection separate from I/O
- **Performance**: High-throughput data handling

### 4. Hardware Abstraction
- **Driver layer**: Isolates hardware-specific code
- **Polymorphism**: Controllers use common motor interface
- **Flexibility**: Easy to swap hardware

### 5. Observer Pattern
- **Live data**: ZMQ publisher broadcasts to subscribers
- **Real-time**: GUI updates during scans
- **Decoupled**: Data source independent of displays

## Threading Model

```mermaid
flowchart TB
    MainThread["Main Thread<br/>(Server Event Loop)"]
    ScanThread["Scan Thread<br/>(Scan Execution)"]
    MonitorThread["Monitor Thread<br/>(Position Logging)"]
    LoggerThread["Logger Thread<br/>(Database Writes)"]
    DataThread["Data Thread<br/>(File I/O)"]

    MainThread -->|Spawn| ScanThread
    MainThread -->|Spawn| MonitorThread
    MainThread -->|Spawn| LoggerThread
    MainThread -->|Spawn| DataThread

    ScanThread -->|Queue| DataThread
    MonitorThread -->|Queue| LoggerThread
    ScanThread -->|Queue| LoggerThread
```

## Configuration Hierarchy

```mermaid
flowchart TD
    MainConfig["main.json<br/>(Server, Beamline Config)"]
    MotorConfig["motors.json<br/>(Motor Definitions)"]
    ScanConfig["scans.json<br/>(Scan Definitions)"]
    DAQConfig["daqs.json<br/>(DAQ Configuration)"]

    MainConfig --> Controller
    MotorConfig --> Controller
    ScanConfig --> Controller
    DAQConfig --> Controller

    Controller --> MotorInstances["Motor Instances"]
    Controller --> ScanInstances["Scan Routines"]
    Controller --> DAQInstances["DAQ Instances"]
```

## File Organization

```
pystxmcontrol/
├── controller/
│   ├── controller.py          # Main controller
│   ├── server.py              # ZMQ server
│   ├── dataHandler.py         # Data management
│   ├── operation_logger.py    # Logging & analytics
│   ├── scans/
│   │   ├── base_scan.py       # Abstract base class
│   │   ├── linear_image.py    # Image scans
│   │   ├── linear_focus.py    # Focus scans
│   │   └── ...
│   └── zmq_publisher.py       # Live data stream
├── drivers/
│   ├── aerotechController.py  # Motor controllers
│   ├── derivedEnergy.py       # Energy motor
│   ├── derivedPiezo.py        # Piezo motors
│   ├── keysightCounter.py     # DAQ devices
│   └── ...
├── gui/
│   ├── mainwindow.py          # Main GUI
│   ├── scanRegion.py          # Scan region widgets
│   └── ...
├── utils/
│   ├── logger.py              # General logging
│   └── stxm.py                # Client API
└── stxmcontrol.py             # Entry point
```

## Extension Points

### Adding a New Scan Type

1. Create class inheriting from `BaseScan`
2. Implement `execute_scan()` method
3. Register in `scans/__init__.py`
4. Add to scan configuration

### Adding a New Motor Driver

1. Create driver class with standard interface
2. Implement `move()`, `getPos()`, `getStatus()`
3. Add configuration to `motors.json`
4. Controller automatically loads it

### Adding a New DAQ

1. Create DAQ driver class
2. Implement `config()`, `start()`, `getData()`
3. Add to `daqs.json`
4. Controller integrates automatically

## Performance Characteristics

- **Scan Rate**: Limited by motor speed and DAQ rate
- **Data Throughput**: ~100 MB/s via ZMQ streaming
- **Command Latency**: <10ms for motor commands
- **Logging Overhead**: <1ms per operation (async)
- **Database**: Monthly rotation prevents bloat
- **Memory**: Streaming minimizes RAM usage

## Fault Tolerance

- **Error Handling**: Graceful degradation on hardware failures
- **Scan Abort**: Clean shutdown on user cancel
- **Data Integrity**: WAL mode for SQLite, atomic HDF5 writes
- **Recovery**: Scans can be resumed from last completed region
- **Logging**: All operations logged for post-mortem analysis

---

**Version**: 1.0
**Date**: 2025-10-31
**Maintainer**: STXM Development Team
