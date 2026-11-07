# Agent Guidelines & Engineering Conventions

This document establishes operating rules, project boundaries, architectural standards, and workflows for all AI coding agents working on this repository. Every agent must read and follow this document before performing any task.

---

## 1. Project Context & Non-Negotiable Boundaries

- **Product Name**: AI Travel Concierge
- **Product Vision**: An AI-powered travel research and planning web application that assists travelers in discovering destinations, researching points of interest, and organizing itineraries.
- **Strict Boundary**: This product is a travel discovery and planning assistant, **NOT a booking engine**.
  - **CRITICAL**: Never claim or imply that a booking, reservation, purchase, payment, cancellation, or ticketing transaction occurred. All outputs, documentation, and user interfaces must respect this boundary.

---

## 2. Phase 1 Scope & Explicit Non-Goals

- **Current Scope**: **Phase 1 Only** (Project Foundation).
- **In Scope for Phase 1**:
  - Repository structure, engineering conventions, and documentation.
  - Frontend foundation: Next.js + React + TypeScript scaffolding and health check interface.
  - Backend foundation: Python + FastAPI + Pydantic scaffolding, health check endpoint, and test harnesses.
  - Local database containerization: PostgreSQL via Docker Compose.
  - Automated CI: GitHub Actions workflow for linting and testing.
- **Explicit Non-Goals (DO NOT IMPLEMENT in Phase 1)**:
  - **No LangGraph or LangChain** workflows or dependencies.
  - **No LLM calls or model integrations** (prompts, API keys, embeddings, inference).
  - **No external travel APIs** (Amadeus, Google Places, Skyscanner, etc.).
  - **No trip persistence** or user-facing itinerary save/edit flows.
  - **No booking or reservation logic**.
  - **No microservices, Kubernetes, Redis, message queues, or distributed multi-agent systems**. Maintain a modular monolith.

---

## 3. Target Repository Layout

Below is the planned repository layout. Items are marked as **[Implemented]** or **[PLANNED]**:

```text
ai-travel-concierge/
├── .editorconfig               # [Implemented] Workspace formatting rules
├── .gitattributes              # [Implemented] Line-ending normalization
├── .gitignore                  # [Implemented] Tracked file exclusion rules
├── AGENTS.md                   # [Implemented] Agent instructions and rules
├── CONTRIBUTING.md             # [Implemented] Solo-developer workflow guidelines
├── README.md                   # [Implemented] Project overview stub
├── docs/                       # [Implemented] Project documentation
│   ├── README.md               # [Implemented] Documentation index
│   ├── architecture.md         # [Implemented] Architecture overview & module seams
│   └── decisions/              # [Implemented] Architecture Decision Records (ADRs)
│       └── 0001-phase1-stack.md# [Implemented] ADR on core stack
├── backend/                    # Backend service root
│   ├── README.md               # [Implemented] Backend placeholder
│   ├── pyproject.toml          # [PLANNED] Python package configuration
│   ├── app/                    # [PLANNED] Application source code (modular monolith)
│   │   ├── main.py             # [PLANNED] FastAPI entry point
│   │   ├── core/               # [PLANNED] Configuration and settings
│   │   └── api/                # [PLANNED] API route definitions (/health)
│   └── tests/                  # [PLANNED] Backend test suite (pytest)
├── frontend/                   # Frontend application root
│   ├── README.md               # [Implemented] Frontend placeholder
│   ├── package.json            # [PLANNED] Node.js dependencies
│   ├── src/                    # [PLANNED] Application source code
│   └── tests/                  # [PLANNED] Frontend test suite
├── .github/                    # GitHub configuration
│   └── workflows/              # [PLANNED] CI pipelines (do not create until workflow is added)
└── docker-compose.yml          # [PLANNED] Local PostgreSQL service container
```

**Rule**: Do not create future planned directories or files until their specific implementation task.

---

## 4. Branching & Git Model

- **`main`**: Production-ready, stable codebase. Direct commits to `main` are strictly forbidden (except the initial repository baseline commit).
- **`develop`**: Integration branch for verified feature work.
- **Topic Branches**: All changes must occur on topic branches cut from `develop`:
  - `feature/<description>`: New functional features or scaffolds.
  - `test/<description>`: Test suite enhancements or additions.
  - `fix/<description>`: Bug fixes and corrections.
  - `docs/<description>`: Documentation additions and updates.
- **Merge Authority**: The solo developer merges branches into `develop` or `main` after review. Agents must never merge into `main` or `develop`.

---

## 5. Git Safety Rules

Agents must observe strict Git safety:
- **Always verify branch status first**: Run `git status --short --branch` before creating or switching branches. If uncommitted changes exist, stop and report.
- **Explicit staging only**: Use `git add <explicit-path> ...`. Never use `git add .` or `git add -A`. A directory add is permitted only when `git status --short` confirms no unintended files exist.
- **Prohibited Git commands**:
  - Never run `git push --force` or `git push --force-with-lease`.
  - Never run `git reset --hard`.
  - Never run `git clean -fd` or `git clean -fdx`.
  - Never run `git checkout -- <path>` or `git restore` on unreviewed work.
  - Never amend (`git commit --amend`) or rebase published history.
  - Never push, open pull requests, merge, or deploy unless explicitly directed and verified.

---

## 6. Conventional Commits

All commit messages must follow the Conventional Commits specification:
```text
<type>(<scope>): <short description>
```
- **Allowed Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- **Scope**: Optional, lowercase component name (e.g., `backend`, `frontend`, `ci`).
- **Examples**:
  - `chore: initialize repository`
  - `docs: add engineering conventions and architecture notes`
  - `feat(backend): add health check endpoint`
  - `test(backend): add test for health endpoint`

---

## 7. Testing Rules

- **Deterministic & Mocked**: Unit tests must never make real external network calls or require live third-party travel APIs. All external interactions must be mocked.
- **No Fabrications**: Never claim a test passed unless you executed the test command and observed a successful exit status. Report unrun tests as "not run".

---

## 8. Security & Privacy Rules

- **No Secrets in Code**: Never commit passwords, tokens, API keys, or private certificates.
- **Environment Files**:
  - `.env` and `.env.*` must be ignored by Git.
  - Only `.env.example` files containing non-sensitive placeholder names may be committed.
- **No Local System Details**: Never write absolute filesystem paths (such as Windows user directories or `/home/...`), usernames, or local machine identifiers into tracked files.

---

## 9. Windows 11 & PowerShell Conventions

- The primary developer environment is **Windows 11 with PowerShell 5.1/7**.
- Use PowerShell-compatible syntax for commands (e.g., `;` for sequence, `Test-Path`, `Get-ChildItem`).
- Provide equivalent Bash commands in documentation where workflows differ across platforms.
- Ensure proper path separator handling (forward slashes `/` work across Git, Node.js, and Python tools on Windows).

---

## 10. Memory vs. Active Inspection Rule

- **Do not assume memory across sessions**: Agents start fresh with no persistent recall of past interactions.
- **Always inspect before acting**:
  - Run `git status --short --branch`, `git branch --show-current`, and `git log --oneline -10`.
  - Check for existing documentation and code before writing.
  - Never assume a file exists or doesn't exist without verifying.
  - Never delete, overwrite, or clobber existing code without understanding its context.

---

## 11. Required Final Report Format

Every task execution must conclude with a final report containing these 8 items in exact order:
1. Summary of changes.
2. Files created / modified / deleted.
3. Commands actually run and their real outcomes.
4. Tests passed, failed, or not run (never claim unrun tests passed).
5. Git branch and working-tree status (`git status --short --branch`).
6. Commit hash if a commit was created (`git log -1 --oneline`), otherwise state "no commit".
7. Any unresolved issues and the exact next step.
8. Confirmation that no secrets or unrelated user files were included.
