# {{PROJECT_NAME}}

Android app project using Kotlin and Gradle.

## Stack
- Kotlin
- Jetpack Compose
- Gradle (Kotlin DSL)
- Material Design 3

## Development Workflow

### Planning (Opus in Claude Code)
1. Describe what you want built
2. Opus writes the PRD to .taskmaster/docs/prd.txt
3. Opus uses Task Master MCP tools to parse PRD into tasks and expand subtasks

### Execution (Gemma 4 via OpenCode)
```bash
sprint status    # View task dashboard
sprint next      # Execute next task with Gemma 4
sprint run       # Execute all tasks autonomously
```

### Review (Opus in Claude Code)
Review changes, fix issues, commit and ship.
