# Traverse: SWE Harbor Take-Home Assignment

## Repo Structure

This repo is a fork of [Verifiers](https://github.com/PrimeIntellect-ai/verifiers), Prime Intellect's framework for training and evaluating AI coding agents with RL. Here's the layout:

```
take-home/
├── verifiers/              # Core Verifiers framework (don't modify)
│   ├── envs/               # Built-in environment types
│   ├── rubrics/            # Reward/scoring infrastructure
│   ├── rl/                 # RL trainers
│   └── ...
├── environments/
│   └── swe_harbor/         # ← YOUR WORKING DIRECTORY
│       ├── swe_harbor.py   # Environment class that loads and runs tasks
│       ├── pyproject.toml  # Project config and dependencies
│       ├── environment/    # Shared Docker environment (Healthchecks app)
│       │   ├── Dockerfile  # Builds the base image
│       │   └── app/        # Healthchecks codebase (pinned at v3.6)
│       └── tasks/          # ← Where you create tasks
│           ├── _template/                # Starter template to copy
│           ├── add-check-annotations/    # Example task
│           └── add-project-transfer/     # Example task
└── README.md               # ← You are here
```

You only need to work inside `environments/swe_harbor/tasks/`. Everything else is supporting infrastructure.

## Shared Codebase

All tasks run against the same codebase: [Healthchecks](https://github.com/healthchecks/healthchecks) (v3.6), an open-source cron job monitoring service written in Python/Django.

The codebase lives in `environment/app/` and gets baked into a Docker image that all tasks share. Tasks themselves are lightweight (just instruction + solution + tests).

## How It Works

**SweHarborEnv** (`environments/swe_harbor/swe_harbor.py`) is the Harbor-format environment that runs tasks. The flow:

1. A Docker container starts from the shared `environment/Dockerfile`.
2. `instruction.md` is mounted into the container.
3. An agent script runs inside the container with tools for bash, reading/writing files, and string replacement. It reads the instruction and attempts to solve the task.
4. When the agent finishes (or times out), `tests/test.sh` runs.
5. pytest executes `test_solution.py` and writes `1` (all pass) or `0` (any fail) to `/logs/verifier/reward.txt`.

The agent only sees `instruction.md`. It never sees the tests.

## Your Task

Create **1-2 original software engineering tasks** in Harbor format under `environments/swe_harbor/tasks/`.

Each task directory needs:

| File | Purpose |
|------|---------|
| `task.toml` | Metadata (difficulty, timeouts) |
| `instruction.md` | The problem statement the agent sees |
| `solution/solve.sh` | Reference solution script |
| `tests/test_solution.py` | Pytest test cases |
| `tests/test.sh` | Test runner (writes reward file) |

**Requirements:**

1. `solve.sh` must pass all tests (reward = 1)
2. Tests must fail without the solution applied (reward = 0)
3. Tests should catch incorrect/incomplete solutions, not just the happy path
4. At least one task should touch multiple files

### Getting Started

1. **Fork this repo** and clone your fork
2. **Look at the examples** in `environments/swe_harbor/tasks/add-check-annotations/` and `add-project-transfer/`
3. **Explore the Healthchecks codebase** at `environments/swe_harbor/environment/app/hc/`
4. **Copy the template**: `cp -r environments/swe_harbor/tasks/_template environments/swe_harbor/tasks/your-task-name`
5. **Fill in each file** following the TODO comments
6. **Test with Docker** (see below)

### Task Design Guidelines

We want tasks that test multi-step problem solving: planning, reading across files, and composing changes that depend on each other. Think "what would take a junior engineer a day", not "write a single function".

Good task types:
- Add a feature (new model + API endpoint + URL routes + tests)
- Debug across files (multiple interacting bugs)
- Extend an existing system with non-trivial new behavior
- Refactor + fix + extend combos

What to aim for:
- The agent needs to touch 3+ files
- Changes in one file affect correctness in another
- Can't be solved by just writing code linearly without reading what's already there
- Partial solutions are possible but won't pass all tests
- 20-40 tests with good edge case coverage

Avoid:
- Leetcode-style puzzles
- Anything needing internet access (containers are isolated)
- Subjective tasks with no clear pass/fail
- Tests so loose the agent can stumble into passing
- Single-function tasks

**Scope:** Think 1-2 hours of focused engineering work. Tasks should require reading and understanding existing code, not just writing new code in isolation.

## Running the Environment

### Prerequisites

- **Docker** installed and running
- **`OPENROUTER_API_KEY`** (only for full framework runs, not needed for Docker-only testing):
  ```bash
  cp environments/swe_harbor/.env.example environments/swe_harbor/.env
  # edit .env with your OpenRouter API key
  ```

### Quick Verification (Docker Only)

Run from `environments/swe_harbor/`:

```bash
cd environments/swe_harbor
```

**Build the image (once):**

```bash
docker build -t swe-harbor environment/
```

**Run with solution (should print `1`):**

```bash
docker run --rm \
    -v $(pwd)/tasks/TASK_NAME/solution:/solution \
    -v $(pwd)/tasks/TASK_NAME/tests:/tests \
    swe-harbor \
    bash -c "mkdir -p /logs/verifier && cd /app && bash /solution/solve.sh && bash /tests/test.sh && cat /logs/verifier/reward.txt"
```

**Run without solution (should print `0`):**

```bash
docker run --rm \
    -v $(pwd)/tasks/TASK_NAME/tests:/tests \
    swe-harbor \
    bash -c "mkdir -p /logs/verifier && bash /tests/test.sh && cat /logs/verifier/reward.txt"
```

If the first prints `1` and the second prints `0`, your task works. If both print `1`, your tests aren't checking anything.

**Example with `add-check-annotations`:**

```bash
docker build -t swe-harbor environment/

# With solution (should print 1)
docker run --rm \
    -v $(pwd)/tasks/add-check-annotations/solution:/solution \
    -v $(pwd)/tasks/add-check-annotations/tests:/tests \
    swe-harbor \
    bash -c "mkdir -p /logs/verifier && cd /app && bash /solution/solve.sh && bash /tests/test.sh && cat /logs/verifier/reward.txt"

# Without solution (should print 0)
docker run --rm \
    -v $(pwd)/tasks/add-check-annotations/tests:/tests \
    swe-harbor \
    bash -c "mkdir -p /logs/verifier && bash /tests/test.sh && cat /logs/verifier/reward.txt"
```

### Full Framework Run (Optional)

To run through the actual Verifiers pipeline with an AI agent:

```bash
# From repo root
uv add verifiers
prime env install swe_harbor --path ./environments/swe_harbor
```

Then run an eval:

```bash
prime eval run swe_harbor -m gpt-4
```

## Harbor Format Reference

### `task.toml`

```toml
version = "1.0"

[metadata]
author_name = "Your Name"
author_email = "you@example.com"
difficulty = "easy"        # easy | medium | hard
category = "programming"
tags = ["python", "django", "rest-api"]

[verifier]
timeout_sec = 180.0        # Max time for test execution

[agent]
timeout_sec = 900.0        # Max time for the agent to work
```

No `[environment]` section needed since all tasks share the same Docker image.

### `instruction.md`

The problem statement the agent receives. Be specific about what files to modify, expected signatures/behavior, and constraints. The agent works against the Healthchecks codebase at `/app/`.

### `solution/solve.sh`

A bash script that produces the correct solution. Runs inside the container at `/app`. Can write files, apply patches, run migrations, etc. Must be deterministic.

### `tests/test.sh`

Standard pattern:

```bash
#!/bin/bash
cd /app
pip install pytest > /dev/null 2>&1
mkdir -p /logs/verifier

# Run migrations in case the solution created new ones
python manage.py migrate --run-syncdb > /dev/null 2>&1

PYTHONPATH=/app DJANGO_SETTINGS_MODULE=hc.settings pytest /tests/test_solution.py -v 2>&1
if [ $? -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
```

### `tests/test_solution.py`

Pytest file using Django's test infrastructure. Extend `BaseTestCase` from `hc.test` for pre-built users, projects, and API keys. Aim for 20-40 tests covering happy paths, edge cases, and error conditions.
