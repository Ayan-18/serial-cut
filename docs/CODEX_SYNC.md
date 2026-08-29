# Codex Sync Between Laptop And Desktop

Use GitHub plus committed project guidance as the shared memory layer.

Official OpenAI documentation says Codex reads `AGENTS.md` before work and that durable project guidance should live in `AGENTS.md` or checked-in docs. Local projects attach folders on one computer, so the reliable cross-computer sync point is the repository.

References:

- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/projects

## One-Time Setup On Each Computer

1. Install Git, Python 3.11, Node.js 22+ or 24+, FFmpeg/ffprobe, and Codex.
2. Clone the repository:

```powershell
git clone git@github.com:Ayan-18/serial-cut.git
cd "serial-cut"
```

3. Create local environment files:

```powershell
Copy-Item .env.example .env
.\scripts\setup.ps1
.\scripts\check_system.ps1
```

4. In Codex Desktop, create or open a local project whose primary folder is this repository folder.

Do not copy `.env`, `.venv`, `data`, original media, model files, or rendered exports through Git. Those stay local to each computer.

## Daily Workflow

Before starting work on either computer:

```powershell
git status --short --branch
git pull --ff-only
```

Ask Codex to read:

- `AGENTS.md`
- `WORKLOG.md`
- `README.md`
- the files related to the task

After meaningful work:

```powershell
.\.venv\Scripts\python.exe -m pytest
Push-Location frontend
npm run build
Pop-Location
git status --short
git add .
git commit -m "Describe the change"
git push
```

If only backend changed, frontend build is optional. If only docs changed, tests are optional, but update `WORKLOG.md` when the change affects project direction.

## Handoff Prompt For A New Codex Task

```text
Продолжи работу над SerialCuts из этого репозитория.

Перед действиями прочитай AGENTS.md, WORKLOG.md, README.md, ARCHITECTURE.md и MODEL_SETUP.md. Сначала проверь git status и, если я попрошу синхронизацию, сделай git pull --ff-only.

Важно: приложение локальное Windows-first; исходные медиа read-only; ничего не отправлять во внешние AI-сервисы; Docker не использовать в MVP; секреты и .env не коммитить.

После изменений обнови WORKLOG.md, запусти релевантные проверки, сделай commit и push, если я это попрошу.
```

## Conflict Rule

If both computers changed the same branch:

1. Stop and inspect `git status`.
2. Do not use destructive reset commands.
3. Pull with rebase or merge only after understanding which files conflict.
4. Keep user changes unless the user explicitly asks to discard them.
