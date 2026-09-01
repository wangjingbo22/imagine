# S3-T009 Independent Acceptance Report

**Task:** S3-T009 account registration and profile

**Date:** 2026-09-01 (Asia/Shanghai)

**Assessed worktree:** `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.worktrees\czy-S3-T009`

**Branch and baseline:** `czy-S3-T009`; `main` / `673a276` plus the uncommitted S3-T009 implementation under assessment.

**Verdict:** `ACCEPTED WITH CONDITIONS / 验收通过（条件）`

The implementation, P1 closure configuration, and targeted regressions meet the S3-T009 acceptance scope. This is not an assertion that all other public features are complete or that the current public instance runs this worktree. The remaining condition is an environment-level Render deployment verification: the target Blueprint must be applied, then a service restart or redeploy must retain a registered account and its profile on the declared Persistent Disk.

## P1-001 Closure Reverification

**Status:** `CLOSED IN REPOSITORY CONFIGURATION; ENVIRONMENT RESTART EVIDENCE NOT RUN`

The former P1 was that the Render API stored the account database on ephemeral storage. The assessed fix closes that configuration gap:

- `render.yaml:7-10` declares a 1 GB `xingzhi-travel-api-data` Persistent Disk mounted at `/app/data`.
- `render.yaml:32-33` explicitly sets `ACCOUNT_SESSION_DB_PATH=/app/data/account.sqlite3` for the API service.
- `docker-compose.prod.yml:18,22,45` uses the same account path and the persistent `xingzhi-data:/app/data` volume.
- `deploy/README.md:30-33` explains that the Blueprint now declares the disk and that the account database uses it.
- `backend/tests/test_s3_t009_account.py:39-59` statically binds the Render disk and account-path contract.

**Independent closure evidence:**

```powershell
# Render configuration parser and semantic assertions
python -c "import yaml; from pathlib import Path; data=yaml.safe_load(Path('render.yaml').read_text(encoding='utf-8')); api=next(item for item in data['services'] if item['name']=='xingzhi-travel-api'); env={item['key']: item.get('value') for item in api['envVars']}; assert api['disk']=={'name':'xingzhi-travel-api-data','mountPath':'/app/data','sizeGB':1}; assert env['ACCOUNT_SESSION_DB_PATH']=='/app/data/account.sqlite3'"

# Docker Compose configuration parser and semantic assertions
python -c "import yaml; from pathlib import Path; data=yaml.safe_load(Path('docker-compose.prod.yml').read_text(encoding='utf-8')); backend=data['services']['backend']; assert backend['environment']['ACCOUNT_SESSION_DB_PATH']=='/app/data/account.sqlite3'; assert 'xingzhi-data:/app/data' in backend['volumes']; assert 'xingzhi-data' in data['volumes']"
```

Both commands passed during this second independent acceptance. Docker CLI was unavailable in the QA environment, so `docker compose config` itself could not be executed; the Compose YAML was parsed and its relevant structure asserted with the same YAML parser used for Render.

**Remaining environment-only evidence:** Apply the Blueprint to the actual Render target, record its `buildSha`, register a disposable account, restart or redeploy the API, and prove `GET /api/v1/account/me` still returns the saved profile. Do not place the Cookie value in the record.

## Acceptance Checklist

| Check | Result | Independent evidence |
| --- | --- | --- |
| Registration, normalized unique email, login, `me`, logout, and profile update | PASS locally | Targeted ASGI suite: `12 passed`; interactive browser flow covered registration, profile save, reload, and logout. |
| Password storage is Argon2id, never plaintext | PASS | `AccountService` uses `PasswordHash.recommended()`; targeted test inspected SQLite and asserted an `$argon2id$` hash different from the submitted password. |
| Opaque session is hashed in the database | PASS | `account_sessions` has only `token_hash`; `hash_session_token()` is SHA-256; targeted test asserts a 64-character stored hash that differs from the Cookie value. |
| 14-day hard upper bound, expiry, and revocation | PASS locally | Settings restrict TTL to 1-14 days; service caps at 14; session query requires `expires_at > now` and `revoked_at IS NULL`; targeted tests cover cap, expiry, and logout revocation. |
| Cookie and cache controls | PASS locally / configuration PASS | `HttpOnly`, `SameSite=Lax`, account-only path, and 14-day `Max-Age` are set; success, application errors, and validation errors are `Cache-Control: no-store`. Production settings reject `AUTH_COOKIE_SECURE=false`; Docker Compose and Render set it true. |
| CORS browser credentials | PASS | API CORS enables credentials for configured origins; targeted preflight test passed; frontend fetch client uses `credentials: 'include'`. |
| Profile allow-list and bounds | PASS | Pydantic models forbid unknown fields, expose only display name, home city, and zero to eight interests. Targeted suite rejects a phone field and nine interests; browser reports the eight-interest client limit. |
| No sensitive-profile inference | PASS within stated scope | No sensitive schema fields or inference logic found. Free-text interests are stored only when explicitly submitted. |
| Account authentication does not grant collaboration access | PASS | Account route uses its own Cookie and service. Existing collaboration routes still require `X-Organizer-Token` or `X-Participant-Session`; targeted ASGI check received `403 ORGANIZER_PERMISSION_REQUIRED` when only an account session was present. |
| Existing collaboration flow regression | PASS | Full backend suite and all 92 frontend tests passed, including collaboration capability/header-contract tests. |
| Frontend route, state, accessibility, and responsive contract | PASS locally | `/account` is routed from the shell. At 375x812, no horizontal overflow occurred, the switch control measured 44px, submit measured 46px, and keyboard focus showed a 3px visible outline. Browser console had no warnings or errors. |
| Production account data persistence | PASS (configuration condition) | Render API declares a 1 GB `/app/data` Persistent Disk and an explicit account DB path; actual Render restart retention remains environment evidence not run. |

## Executed Evidence

All Python commands used the existing project runtime at `C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe`. Pytest's normal `%TEMP%` directory was inaccessible in the managed environment, so each command used a fresh `--basetemp` directory inside the isolated worktree; those directories were removed after execution.

| Command | Result |
| --- | --- |
| `python -m pytest -q --basetemp .qa-tmp-s3-t009 backend/tests/test_s3_t009_account.py` | `12 passed in 3.89s` |
| `python -m pytest -q --basetemp .qa-tmp-s3-t009-full-rerun` | `766 passed, 2 skipped in 79.11s` |
| `frontend> npm.cmd test` | `92 passed, 0 failed` |
| `frontend> npm.cmd run lint` | Exit 0; two pre-existing warnings in `ConversationPlannerPage.tsx` at lines 135 and 330, outside S3-T009. |
| `frontend> npm.cmd run build` | Exit 0; `tsc -b` and Vite production build completed. |

### Second-Round P1 Closure and Boundary Evidence

| Command | Result |
| --- | --- |
| `python -m pytest -q --basetemp .qa-tmp-s3-t009-round2-account backend/tests/test_s3_t009_account.py` | `13 passed in 4.11s`, including `test_render_persists_account_database_on_the_api_data_disk`. |
| `python -m pytest -q --basetemp .qa-tmp-s3-t009-round2-collab backend/tests/test_s2_t003_http_boundaries.py` | `10 passed in 4.19s`; organizer and member capability-header HTTP boundaries remain intact. |
| Render YAML semantic parser assertion | PASS: disk `{name: xingzhi-travel-api-data, mountPath: /app/data, sizeGB: 1}` and `ACCOUNT_SESSION_DB_PATH=/app/data/account.sqlite3`. |
| Docker Compose YAML semantic parser assertion | PASS: `ACCOUNT_SESSION_DB_PATH=/app/data/account.sqlite3`, `xingzhi-data:/app/data`, and declared named volume. |
| `frontend> npm.cmd test` | `92 passed, 0 failed`. |
| `frontend> npm.cmd run build` | Exit 0; `tsc -b` and Vite production build completed. |

The first raw test invocation could not start because the PATH-selected MSYS Python lacked pytest. The project virtual environment was then located and used. A first project-runtime invocation failed before any test body because the sandbox denied `%TEMP%\\pytest-of-lenovo`; rerunning with the in-worktree `--basetemp` produced the results above. These are test-environment constraints, not product failures.

## Browser Acceptance Flow

The local API ran at `127.0.0.1:8019` with an isolated account database. Vite ran at `127.0.0.1:5189` using its same-origin `/api` proxy.

1. Opened `/account` without a Cookie: the page moved from its loading state to the login form without showing a false error.
2. Submitted a valid-format unknown email and wrong password: visible error was `邮箱或密码不正确`.
3. Registered a disposable local account, then observed the signed-in profile view.
4. Saved display name, `北京`, and three interests; reloaded the page and observed all values restored through `GET /me`.
5. Submitted nine interests and observed `兴趣最多填写 8 项`; logged out; reloaded and observed the login form.
6. At 375x812, verified no horizontal overflow, visible focus outline, touch-size constraints, and no browser-console errors.

## Residual Risks and Deliberate Non-goals

- Actual Render deployment verification remains unexecuted: apply the target Blueprint, record the target `buildSha`, verify the production `Secure` Cookie, then restart or redeploy the API and prove the account/profile remains available. This is an environment-level release check, not a requirement to complete unrelated public features.
- Email verification, password recovery, OAuth, RBAC, old-trip/member binding, sensitive profiling, and automatic preference inference are deliberate non-goals for this scope.
- Brute-force throttling and account lockout are not supplied by this scope; product security owners should decide whether they are required before any broader public rollout.
- P1-001 is closed in repository configuration. The remaining restart-persistence observation is a condition on a real Render deployment, not a remaining code or configuration defect.

## QA Hygiene

No production source, dependency, deployment configuration, or existing test was modified by either acceptance run. The second round only updated this report. The temporary pytest directories are removed before handoff; this report remains the only QA-authored file.
