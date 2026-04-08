# {{PROJECT_NAME}}

Static website project.

## Stack
- HTML5, CSS3, JavaScript
- No build tools required
- Can be extended with any framework

## Development Workflow

This project uses an automated sprint workflow:

```bash
sprint plan      # Write PRD, parse into tasks (Gemma 4)
sprint status    # View task dashboard
sprint next      # Execute next task (Gemma 4 via OpenCode)
sprint run       # Execute all tasks autonomously
sprint review    # Launch Claude Code to review changes
```

### How it works
1. Describe what you want built — Opus writes the PRD
2. Run `sprint plan` — Gemma 4 breaks it into tasks
3. Run `sprint next` or `sprint run` — Gemma 4 implements via OpenCode
4. Review changes and ship
