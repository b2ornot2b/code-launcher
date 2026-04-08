# {{PROJECT_NAME}}

Hybrid cloud + mobile project.

## Structure
- `backend/` — Cloud infrastructure and API (Terraform + FastAPI)
- `mobile/` — Mobile app (Flutter or native)

## Stack
- Terraform for cloud infra
- FastAPI for backend API
- Flutter or Kotlin for mobile

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
