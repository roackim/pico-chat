## AI Harness + Podman Implementation Summary

### Goal

Run an AI agent inside an isolated, reproducible container while allowing it to work on a host project directory without affecting the host system.

### Components

* **Podman**: OCI-compatible, daemonless, rootless container engine.
* **Containerfile/Dockerfile**: Defines the development environment.
* **AI Harness**: Orchestrates container lifecycle and communication.
* **Workspace**: Host project mounted into the container.

### Container Lifecycle

```text
Build Image
      ↓
Create Container
      ↓
Mount Project
      ↓
Run AI Agent
      ↓
Monitor / Interact
      ↓
Collect Results
      ↓
Destroy Container
```

### Harness Responsibilities

* Build images (`podman build`)
* Start/stop containers (`podman run`, `stop`, `rm`)
* Mount project directory (`-v`)
* Set working directory (`-w`)
* Inject environment variables/secrets
* Stream logs (`podman logs -f`)
* Execute commands (`podman exec`)
* Inspect status (`ps`, `top`, `stats`, `inspect`)
* Clean up after execution

### Development Environment

Defined in a `Containerfile` (or `Dockerfile`):

* Base OS
* Language runtime(s)
* Package manager
* AI tooling
* Project dependencies
* Build tools
* Default entrypoint

The build file can have any name:

```bash
podman build -f ai.containerfile -t agent .
```

### Workspace

```
Host
└── project/
      │
      ▼
Container
└── /workspace
```

The AI modifies only the mounted project. Everything else is ephemeral.

### Observation

The harness can monitor execution using:

* `podman logs -f`
* `podman top`
* `podman stats`
* `podman exec`
* `podman inspect`

### Security

* Rootless containers
* Mount only required directories
* Limit environment variables
* Optional read-only filesystem
* Optional network isolation (`--network=none`)
* Disposable containers (`--rm`)

### Suggested Harness API

```text
build(image, containerfile)

create(image)

mount(hostPath, containerPath)

run(command)

exec(command)

logs()

stats()

inspect()

stop()

destroy()
```

### Architecture

```text
User
  │
  ▼
AI Harness
  │
  ├── Build image
  ├── Start container
  ├── Mount workspace
  ├── Launch AI agent
  ├── Stream logs/events
  ├── Execute additional commands
  └── Destroy container
          │
          ▼
     Rootless Podman
          │
          ▼
 Isolated Development Environment
```

### Benefits

* Reproducible environments
* Host remains clean
* Strong isolation for AI-generated code
* Supports multiple concurrent agents
* Compatible with existing Dockerfiles and OCI images
* Lightweight, daemonless workflow suitable for local development and CI
