Core Architectural Mandates (Non-Negotiable)
1. The Single Responsibility & Size Mandate
You must aggressively enforce the Single Responsibility Principle (SRP).

No Monolithic Classes: A class should have only one reason to change. If a class manages file state, it should not also handle file copying logic or API endpoint definitions.

Strict Size Limits: As a hard rule, if you find yourself writing or modifying a class that is growing beyond 250 lines of code, or a function beyond 50 lines, you must stop. Your first action should be to propose a refactoring plan to break it down into smaller, more focused classes or functions that adhere to SRP.

2. The Dependency Inward Mandate
You must enforce a strict, one-way dependency flow.

Core logic is independent: The core business logic (e.g., FileStateService, FileCopyService, TrackedFile model) located in the application's core modules must never, under any circumstances, import from or depend on outer layers like FastAPI, WebSockets, or specific database clients.

Interfaces are key: Communication across boundaries (e.g., from the API layer to a service) must happen through abstract interfaces (using Python's Protocols /abc module if necessary), not concrete classes.

3. The Proactive Refactoring Mandate
Your role is proactive, not just reactive.

Identify and Report Violations: If you are asked to add a feature to a piece of code that already violates these mandates (e.g., adding more logic to an oversized class), your first responsibility is to report the existing "code smell" and propose a refactoring plan.

Justify Your Design: For any new class or significant function, add a brief comment explaining how it adheres to these principles. Example: # This class is responsible solely for monitoring the source directory, adhering to SRP.

Never use local imports in classes / methods: Avoid local imports that break the dependency flow. If you find yourself needing to import a module from a higher layer, it's a sign that the architecture needs adjustment.

# Project: Python File Transfer Agent

## 1. Project Overview

The goal is to build a robust, automated background service in Python. Its primary function is to reliably move video files (MXF) from a local source folder (and growing while they are being created) on macOS to a network-attached storage (NAS) destination. The service must be resilient to network failures and restarts. The architecture is heavily inspired by Clean Code and SOLID principles.

## 2. Core Architecture & Python Stack

The application is built using Python with FastAPI for the API/UI layer and `asyncio` for concurrent background tasks.

- **Central State Management**: The application's "single source of truth" is a singleton-like `FileStateService`. This service manages a list of `TrackedFile` objects.
    - `TrackedFile` should be a Pydantic model representing a file's metadata (path, status, size, progress, etc.).
    - `FileStatus` should be an Enum with states like `Discovered`, `Ready`, `InQueue`, `Copying`, `Completed`, `Failed`.

- **Producer/Consumer Pattern**: The core logic is split into two decoupled background services (running as `asyncio` tasks):
    1.  **Producer (`FileScannerService`)**: Polls the source directory, identifies "stable" files, and adds their paths to a job queue.
    2.  **Consumer (`FileCopyService`)**: Takes file paths from the job queue and performs the copy operation.

- **Job Queue**: The producer and consumer are decoupled using an `asyncio.Queue`. This queue is registered as a singleton to ensure a single, shared instance.

- **Configuration**: All key parameters (SourcePath, DestinationPath, PollingIntervalSeconds, etc.) must be loaded from a configuration file (e.g., `config.json` or an `.env` file).

## 3. Key Logic & Principles

- **File Stability Logic**: A file is considered "stable" and ready to be copied only when its modification time (`os.path.getmtime`) has not changed for a configured duration (`FileStableTimeSeconds`).

- **Robust Error Handling**:
    - **Global Errors (e.g., destination unavailable)**: The `FileCopyService` must pause all operations and enter an infinite retry loop with a long, configurable delay.
    - **Local Errors (e.g., source file is locked)**: The service should attempt to copy a specific file a limited number of times (e.g., 3 retries) with short delays. If it fails all retries, the file's status is set to `Failed`, and the service moves to the next job.

- **Safe File Copy**: When copying, first write to a temporary file (e.g., `filename.mxf.tmp`). Only after a successful copy and a file size verification (source vs. destination) should the temporary file be renamed to its final name and the original source file be deleted.

- **API & Real-time UI**: The FastAPI app exposes API endpoints (e.g., `/api/status`, `/api/health`). For the UI, the backend should push real-time state updates to the frontend using **WebSockets**.

## Core Principles

- **Structure with `APIRouter`**: The application is modular. Each resource or domain (e.g., users, items) has its own router file in the `app/routers/` directory.

- **Central Entrypoint**: `app/main.py` is the main entry point that imports and includes all `APIRouter` instances into the primary `FastAPI` app.

- **Dependency Injection**: Reusable logic, like database sessions or authentication wirering up classes ang background services), is placed in `app/dependencies.py` and injected into path operations using `Depends()`.

- **Type Hints**: Always use Python type hints for function parameters, return values, and Pydantic models to ensure data validation and code clarity.


Code Smell Definitions & Directives
Reference this list to identify and avoid common "code smells". Your goal is to actively refactor code to eliminate these issues whenever you encounter them.

Bloaters (Code that is too big)
Long Method: A function that has grown too long and does too many things; break it into smaller, single-purpose functions.

Large Class: A class with too many responsibilities, fields, or methods; split it into smaller, more cohesive classes.

Primitive Obsession: Relying on primitive data types instead of creating small, dedicated objects for domain concepts (e.g., using a string for an email instead of an EmailAddress class).

Long Parameter List: A function with an excessive number of parameters; group related parameters into a dedicated object or data class.

Data Clumps: Groups of variables that are always passed around together; encapsulate them into their own class or data structure.

Object-Orientation Abusers (Incorrect use of OOP)
Alternative Classes with Different Interfaces: Two or more classes that perform similar functions but have different method names; unify them under a common interface or superclass.

Refused Bequest: A subclass that uses only a few methods from its superclass, ignoring the rest; inheritance is likely the wrong abstraction.

Switch Statements: Using switch statements or long if/elif chains to handle different types or states; replace this with polymorphic objects or a strategy pattern.

Temporary Field: A class instance variable that is only set and used during a specific operation; this indicates the class has more than one responsibility.

Change Preventers (Changes have a high blast radius)
Divergent Change: One class is frequently changed in different ways for different reasons; this indicates it should be split by responsibility.

Parallel Inheritance Hierarchies: Every time you create a subclass for one class, you must also create a subclass for another; aim to merge the two hierarchies.

Shotgun Surgery: A single conceptual change requires making small modifications to many different classes; consolidate the related logic into a single, cohesive class.

Dispensables (Code that should be removed)
Comments: Using comments to explain complex or poorly named code; refactor the code to be self-explanatory instead.

Duplicate Code: The same or very similar code exists in more than one location; extract it into a single, reusable function or method.

Data Class: A class that only holds data while other classes manage its behavior; move the related behavior into the data class itself.

Dead Code: A variable, parameter, function, or class that is no longer used; delete it.

Lazy Class: A class that isn't doing enough to justify its existence; inline its functionality into the class that uses it.

Speculative Generality: An abstract class, interface, or parameter that was created for future features that never materialized; remove the unnecessary abstraction.

Couplers (Code that is too tightly connected)
Feature Envy: A method that accesses the data of another object more than its own; move the method to the class it is "envious" of.

Inappropriate Intimacy: One class relies on the private fields or methods of another class; reduce coupling by using public interfaces and better encapsulation.

Incomplete Library Class: Needing to add functionality to a third-party library class you cannot modify; create a local wrapper or adapter class instead of scattering utility functions.

Message Chains: A long chain of method calls (e.g., object.get_part().get_sub_part().do_work()); this creates tight coupling and should be hidden behind a single method.