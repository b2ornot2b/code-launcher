# {{PROJECT_NAME}}

Python CLI tool.

## Stack
- Python 3.11+
- Click or argparse for CLI
- pyproject.toml for packaging

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
