# Contributing to Maven Core

Thank you for your interest in contributing to Maven Core! This document provides guidelines and instructions for contributing.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Node.js** 20.0.0 or higher
- **Docker** (for running the agent container)
- **Bun** (for agent development)
- **Wrangler CLI** (installed via npm)

## Getting Started

### 1. Fork and Clone

```bash
git clone https://github.com/YOUR_USERNAME/maven-core.git
cd maven-core
```

### 2. First-Time Setup

Run the setup script to install dependencies, generate keys, and initialize the database:

```bash
npm run setup
```

This will:
- Install all dependencies
- Build all packages
- Generate RS256 JWT keypair for local development
- Create `.dev.vars` files with the generated keys
- Run database migrations

### 3. Start Development Servers

```bash
npm run dev:start   # Start all servers in background
npm run dev:status  # Check server status
npm run dev:logs    # Tail all logs
npm run dev:stop    # Stop all servers
```

## Code Style

- **TypeScript** - All code should be written in TypeScript with strict type checking
- **ESLint** - Run `npm run lint` to check for linting issues
- **Formatting** - Use consistent formatting (Prettier recommended)

### Naming Conventions

- Use `camelCase` for variables and functions
- Use `PascalCase` for classes and type definitions
- Use `UPPER_SNAKE_CASE` for constants
- Use descriptive names that reflect the purpose

## Testing

Run tests before submitting a pull request:

```bash
npm run test        # Run all tests
npm run typecheck   # Type check all packages
npm run lint        # Lint all packages
```

## Making Changes

### Branch Naming

Use descriptive branch names:
- `feat/add-new-skill-type` - New features
- `fix/auth-token-expiry` - Bug fixes
- `docs/update-readme` - Documentation updates
- `refactor/simplify-routing` - Code refactoring

### Commit Messages

Write clear, concise commit messages:
- Use the present tense ("Add feature" not "Added feature")
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
- Keep the first line under 72 characters
- Reference issues when applicable

Examples:
```
feat: add OAuth support for MCP connectors

fix: resolve JWT token refresh race condition

docs: update installation instructions
```

## Pull Request Process

1. **Create a feature branch** from `main`
2. **Make your changes** following the code style guidelines
3. **Test your changes** locally
4. **Update documentation** if needed
5. **Submit a pull request** with a clear description

### PR Description Template

Your PR description should include:
- **Summary**: What does this PR do?
- **Test plan**: How was this tested?
- **Related issues**: Link any related issues

## Architecture Overview

See the [README.md](README.md) and [CLAUDE.md](CLAUDE.md) for detailed architecture documentation.

### Key Packages

| Package | Description |
|---------|-------------|
| `@maven/shared` | Shared types, crypto, validation |
| `@maven/control-plane` | Admin API, auth, tenant management |
| `@maven/tenant-worker` | Per-tenant chat routing |
| `@maven/agent` | Agent container with Claude SDK |

## Reporting Issues

When reporting issues, please include:
- A clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Node version, etc.)

## Security

For security vulnerabilities, please see [SECURITY.md](SECURITY.md) for our responsible disclosure process.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

## Questions?

Feel free to open an issue for questions or discussions about the project.
