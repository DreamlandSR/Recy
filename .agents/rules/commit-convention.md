# Universal Conventional Commit Specification

A standardized, professional specification for writing clean, readable, and automated-tool-friendly Git commit messages across any tech stack (Frontend, Backend, Mobile, DevOps, and Full-Stack).

---

## Commit Message Structure

Every commit message consists of a **header**, an optional **body**, and an optional **footer**:

```text
<type>(<scope>): <short description in imperative mood>

[optional body: detailed explanation of the what and why]

[optional footer: breaking changes or issue tracker references]
```

---

## Commit Types (`<type>`)

| Type | Name | Purpose / When to Use | Example |
| :--- | :--- | :--- | :--- |
| **`feat`** | Feature | Introducing a new feature or functionality | `feat(auth): add OAuth2 Google login support` |
| **`fix`** | Bug Fix | Fixing a bug or unexpected error in production or dev | `fix(api): resolve memory leak on file upload stream` |
| **`docs`** | Documentation | Documentation changes only (README, API docs, inline comments) | `docs(readme): add installation guide for docker setup` |
| **`style`** | Code Style | Changes that do not affect code logic (formatting, semicolons, whitespace) | `style(linter): apply prettier formatting across components` |
| **`refactor`** | Refactoring | Code change that neither fixes a bug nor adds a feature | `refactor(db): rewrite query builder for cleaner separation` |
| **`perf`** | Performance | Code change that improves performance or execution speed | `perf(image): optimize image compression before cloud upload` |
| **`test`** | Testing | Adding missing tests or correcting existing test suites | `test(user): add unit tests for password hashing policy` |
| **`build`** | Build System | Changes to build tools, dependencies, or bundlers (`npm`, `composer`, `pip`, `cargo`) | `build(deps): bump tailwindcss from v3 to v4` |
| **`ci`** | Integration | Changes to CI/CD workflows and deployment scripts (`GitHub Actions`, `Docker`, `K8s`) | `ci(actions): add automated testing workflow on pull request` |
| **`chore`** | Maintenance | Repository maintenance, updating `.gitignore`, or config tweaks | `chore(repo): update gitignore and environment templates` |
| **`revert`** | Revert | Reverting a previous commit | `revert(auth): revert "feat(auth): add 2FA verification"` |

---

## Scopes Guidelines (`<scope>`)

Scopes are optional but strongly recommended to pinpoint the affected module or layer across any stack:

### 1. Full-Stack / Web Applications
- **Frontend / UI**: `ui`, `components`, `pages`, `styles`, `router`, `state`
- **Backend / API**: `api`, `auth`, `db`, `models`, `controllers`, `services`, `middleware`
- **DevOps / Infra**: `docker`, `ci`, `deps`, `config`, `env`

### 2. Multi-Stack Examples
- **React / Next.js / Vue**: `feat(components): add responsive navbar modal`
- **Laravel / Symfony**: `fix(controller): resolve null pointer on user profile update`
- **Node.js / Express**: `feat(middleware): add rate limiting on auth endpoints`
- **Python / Django / FastAPI**: `refactor(schemas): update Pydantic response models`
- **Flutter / React Native**: `fix(navigation): fix deep link routing on iOS`
- **Go / Rust / C++**: `perf(pool): implement worker pool for async job queue`

---

## Core Rules & Best Practices

1. **Use Imperative Mood in Subject**:
   - Write as if giving a command or instruction.
   - ✅ `add user registration endpoint`
   - ❌ `added user registration endpoint` or `adding user registration`

2. **Keep Header Short (50–72 characters)**:
   - Clear, concise, and easy to read in `git log --oneline` or GitHub PR timeline.

3. **Lowercase Subject**:
   - Start the description with a lowercase letter after the colon (`:`).
   - ✅ `fix(api): handle connection timeout`
   - ❌ `fix(api): Handle Connection Timeout.`

4. **No Ending Period**:
   - Do not end the header line with a period (`.`).

5. **Handling Breaking Changes**:
   - Append `!` after type/scope for breaking changes, or write `BREAKING CHANGE:` in the footer:
     ```text
     feat(api)!: remove deprecated v1 authentication endpoints

     BREAKING CHANGE: The /api/v1/login endpoint is removed. Use /api/v2/auth/token instead.
     ```

---

## Real-World Commit Examples Cheat Sheet

```bash
# Feature Addition
git commit -m "feat(auth): implement JWT token refresh flow"

# Bug Fix
git commit -m "fix(payment): resolve race condition during webhook processing"

# Performance Optimization
git commit -m "perf(database): add index on user_email column for fast lookup"

# Refactoring
git commit -m "refactor(service): extract payment gateway into separate strategy class"

# Documentation
git commit -m "docs(api): update OpenAPI spec for v2 endpoints"

# Dependencies & Build
git commit -m "build(deps): update laravel framework to v11.x"

# CI/CD Workflow
git commit -m "ci(github): add automated security vulnerability scanner"
```
