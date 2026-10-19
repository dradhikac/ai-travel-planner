# Contributing to AI Travel Concierge

This document outlines the development workflow and engineering guidelines for AI Travel Concierge. The project is currently maintained by a solo developer.

---

## Branching Strategy

Development follows a simplified Git-flow model:
- `main`: Stable, release-ready code.
- `develop`: Primary integration branch.
- Topic branches: All development occurs on branches branched from `develop`:
  - `feature/<feature-name>`: Scaffolding and new functionality.
  - `fix/<issue-name>`: Bug fixes and corrections.
  - `docs/<doc-name>`: Documentation updates.
  - `test/<test-name>`: Test suite creation and modifications.

### Dedicated Branch vs. Small Fix
- **Dedicated Topic Branch (Required)**: For any functional code changes, dependencies, refactoring, test additions, or multi-file documentation work.
- **Direct Commit on Develop (Exception Only)**: Minor, single-line documentation corrections (such as fixing a typo in an existing markdown file) may be committed directly to `develop` only when explicitly authorized. In all other scenarios, use a topic branch.

---

## Commit Guidelines

All commits must adhere to the [Conventional Commits](https://www.conventionalcommits.org/) specification:
```text
<type>(<optional-scope>): <description>
```
Common types:
- `feat`: New user-facing or architectural capability.
- `fix`: Bug fix.
- `docs`: Documentation changes.
- `test`: Adding or updating test cases.
- `chore`: Repository maintenance, configuration, or tooling.

Keep commit messages concise, imperative, and focused on a single change set.

---

## Developer vs. QA Separation

To maintain quality and safety on a solo-developer project:
1. **Developer Phase**:
   - Work strictly within a topic branch.
   - Implement the scoped change and write associated tests.
   - Run local verifications and ensure clean diffs (`git diff --check`).
   - Create a clean commit on the topic branch without pushing or merging.
2. **Review / QA Phase**:
   - Inspect changes against the target branch (`git diff develop...<topic-branch>`).
   - Run verification checks, linters, and automated test suites.
   - Verify that no secrets, temporary files, or absolute local paths were introduced.
   - Perform the merge into `develop` once all checks pass.

---

## Pre-Merge Checklist

Before merging any topic branch into `develop`, verify:
- [ ] `git status --short --branch` confirms a clean working tree.
- [ ] `git diff --check` produces no whitespace or conflict marker errors.
- [ ] Automated tests pass (`pytest` for backend, `npm test` for frontend once implemented).
- [ ] No `.env`, secret credentials, personal files, or build artifacts are tracked.
- [ ] No absolute local file paths or user profile paths exist in committed files.
- [ ] All relative links in markdown documentation resolve to existing files.

---

## Licensing

No open source or commercial license has been selected for this project yet. All rights are reserved. Do not add license headers or license files until a formal decision is recorded.
