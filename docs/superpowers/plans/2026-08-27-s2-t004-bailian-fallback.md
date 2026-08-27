# S2-T004 Bailian Failure Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 T002 对话理解增加 10 秒硬超时、最多一次临时传输重试、严格 proposal 校验和保留固定六问的零权威写入降级。

**Architecture:** T002 在 `answerRevision` 边界拥有持久化和幂等 claim；`StrictTripUnderstandingGateway` 只编排最多两次传输尝试并严格校验 `TripUnderstandingProposal`；现有 `BailianTripDraftExtractor` 复用同一个 `httpx.AsyncClient` 发出请求。成功 proposal 交回 T002，失败返回 `FixedQuestionFallback`；只有成功结果才允许 T002 推进 canonical `TripDraftRevision`。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic v2、httpx、asyncio、pytest、pytest-asyncio、T002 既有 SQLite store。

## Global Constraints

- 实施基线必须先包含 T002 的 answer revision、原子幂等 outcome 和 conversation route；T004 不创建第二套 revision store。
- `BAILIAN_REQUEST_TIMEOUT_SECONDS` 默认 `10.0`，且只接受 `8.0..12.0`（含端点）。
- 每次传输尝试使用相同的 `httpx` timeout 和 `asyncio.timeout` 硬截止；最多两次尝试，不 sleep、不 backoff、无第三次调用。
- 只有 timeout、`httpx.TransportError`、HTTP 429、HTTP 500–599 可以再尝试一次；401/403、其他 4xx 和全部内容错误不得重试。
- fenced JSON、非 JSON、strict Schema 失败、证据/语义失败不得 strip、修复或发 repair prompt。
- 成功只返回 current main 的严格非权威 `TripUnderstandingProposal`；失败必须 `understanding=null`、`canPlan=false` 并保留原始输入和六问原答案。
- 失败只允许 T002 写其既有 answer submission/idempotency outcome；canonical `TripDraftRevision`、Trip、Constraint、PlanVersion、workflow、T003 confirmation 和 Provider 必须零写入/零调用。
- 复用 `app/infrastructure/bailian.py::BailianTripDraftExtractor`、`app/application/llm_gateway.py`、`ConversationSubmission` 和 `TripUnderstandingRequest/Proposal`；不新增重复客户端或依赖。
- 不改 UI；不记录或返回 API Key、Authorization、provider body、完整 prompt、六问全文或模型原文。
- 旧 `/api/v1/trips/drafts/*` 保持兼容；不重构旧 S1 链。

## Preflight: T002 Handoff Gate

代码窗口先执行：

```powershell
git branch --show-current
git rev-parse HEAD
git status --porcelain=v1
rg -n "answerRevision|answer_revision" app backend/tests
rg -n "TripDraftRevisionPort|submit_participant_conversation" app backend/tests
rg -n "trips/conversations" app/api backend/tests
```

期望：代码分支、基线符合派单且工作树 clean；T002 已有 `answerRevision`、conversation service/store 和 organizer route；T003 的 `TripDraftRevisionPort` 仍存在。若 T002 的 concrete service 文件名不是本计划使用的 `app/application/trip_draft_revision_service.py`，Task 4 只映射到 T002 已落地的唯一 concrete service，禁止新建同义 service。

---

### Task 1: Strict Result Contract and Gateway

**Files:**
- Modify: `app/domain/trip_draft.py`
- Modify: `app/application/llm_gateway.py`
- Create: `backend/tests/test_s2_t004_trip_understanding_gateway.py`

**Interfaces:**
- Consumes: `TripUnderstandingRequest`, `TripUnderstandingProposal`, `validate_trip_understanding()`.
- Produces: `TripUnderstandingFailureCode`, `TripUnderstandingGatewayResult`, `TripUnderstandingTransportError`, `TripUnderstandingModelClient`, `TripUnderstandingGateway`, `StrictTripUnderstandingGateway`, `UnavailableTripUnderstandingGateway`.

- [ ] **Step 1: Write failing contract/gateway tests**

Create `backend/tests/test_s2_t004_trip_understanding_gateway.py`. Reuse `backend/tests/fixtures/trip_understanding/one_participant.json` and construct `rawConversation` from its `fieldEvidence[].sourceText`, matching `test_trip_understanding_schema.py`. Implement these exact tests:

| Test name | Setup | Required assertions |
|---|---|---|
| `test_gateway_result_rejects_inconsistent_decision_shape` | construct `MODEL_PROPOSAL` with `proposal=None`, then fallback with `callCount=-1` and `3` | every construction raises `ValidationError` |
| `test_valid_understanding_proposal_is_validated_once_and_returned` | queue one valid fixture JSON | `MODEL_PROPOSAL`, proposal equals strict fixture, both call counts are 1 |
| `test_retryable_transport_failure_recovers_on_the_second_attempt` | queue retryable `LLM_UNAVAILABLE`, then valid JSON | proposal succeeds and both call counts are 2 |
| `test_two_retryable_transport_failures_stop_at_two_calls` | queue three retryable timeouts | fallback `LLM_TIMEOUT`; third outcome remains unused; both call counts are 2 |
| `test_non_retryable_transport_failure_stops_at_one_call` | queue non-retryable `LLM_AUTH_FAILED`, then valid JSON | fallback auth failure; both call counts are 1 |
| `test_invalid_model_content_never_starts_a_repair_call` | parameterize `not-json`, fenced `{}`, and incomplete schema; queue valid JSON second | failure code is respectively invalid JSON, invalid JSON, Schema invalid; both call counts are 1 |
| `test_evidence_context_mismatch_is_content_invalid_without_retry` | mutate one `USER_TEXT.sourceText` outside request, then queue valid JSON | `LLM_CONTENT_INVALID`; both call counts are 1 |
| `test_unconfigured_understanding_gateway_returns_zero_call_fallback` | use `UnavailableTripUnderstandingGateway` | `FIXED_QUESTIONS`, `LLM_NOT_CONFIGURED`, `callCount=0`, `model=None` |

Use this counting fake:

```python
class SequenceUnderstandingClient:
    model = "qwen-fixture"

    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.outcomes = outcomes
        self.call_count = 0

    async def propose_trip_understanding(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
```

每个内容错误测试都在队列中放入第二个合法响应，并断言 `result.call_count == client.call_count == 1`，证明没有 repair call。

- [ ] **Step 2: Run the tests and verify missing symbols**

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_trip_understanding_gateway.py
```

Expected: collection fails because the T004 result/gateway symbols do not exist.

- [ ] **Step 3: Add the strict result contract**

In `app/domain/trip_draft.py`, add the failure alias near the understanding aliases and the result after `TripUnderstandingProposal`:

```python
TripUnderstandingFailureCode = Literal[
    "LLM_NOT_CONFIGURED",
    "LLM_TIMEOUT",
    "LLM_AUTH_FAILED",
    "LLM_UNAVAILABLE",
    "LLM_INVALID_RESPONSE",
    "LLM_INVALID_JSON",
    "LLM_SCHEMA_INVALID",
    "LLM_CONTENT_INVALID",
]


class TripUnderstandingGatewayResult(UnderstandingContractModel):
    decision: Literal["MODEL_PROPOSAL", "FIXED_QUESTIONS"]
    proposal: TripUnderstandingProposal | None
    failure_code: TripUnderstandingFailureCode | None
    call_count: int = Field(ge=0, le=2)
    model: str | None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "TripUnderstandingGatewayResult":
        if self.decision == "MODEL_PROPOSAL":
            valid = (
                self.proposal is not None
                and self.failure_code is None
                and 1 <= self.call_count <= 2
            )
        else:
            valid = self.proposal is None and self.failure_code is not None
        if not valid:
            raise ValueError("trip understanding gateway result is inconsistent")
        return self
```

Export both names in `__all__`.

- [ ] **Step 4: Implement the strict application gateway**

In `app/application/llm_gateway.py`, add:

```python
class TripUnderstandingTransportError(RuntimeError):
    def __init__(
        self,
        code: TripUnderstandingFailureCode,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class TripUnderstandingModelClient(Protocol):
    model: str

    async def propose_trip_understanding(
        self,
        request: TripUnderstandingRequest,
    ) -> str:
        pass


class TripUnderstandingGateway(Protocol):
    async def understand(
        self,
        request: TripUnderstandingRequest,
    ) -> TripUnderstandingGatewayResult:
        pass
```

Implement `StrictTripUnderstandingGateway(client, max_transport_attempts=2)` using the existing candidate gateway's loop. The core must be:

```python
while call_count < self._max_transport_attempts:
    call_count += 1
    try:
        raw = await self._client.propose_trip_understanding(trusted_request)
    except TripUnderstandingTransportError as error:
        if error.retryable and call_count < self._max_transport_attempts:
            continue
        return _understanding_fallback(error.code, call_count, self._client.model)
    except Exception as error:
        logger.warning(
            "trip understanding client failed with %s",
            type(error).__name__,
        )
        return _understanding_fallback(
            "LLM_UNAVAILABLE", call_count, self._client.model
        )

    try:
        proposal = TripUnderstandingProposal.model_validate_json(raw, strict=True)
    except ValidationError as error:
        code: TripUnderstandingFailureCode = (
            "LLM_INVALID_JSON"
            if any(item["type"] == "json_invalid" for item in error.errors())
            else "LLM_SCHEMA_INVALID"
        )
        return _understanding_fallback(code, call_count, self._client.model)
    try:
        proposal = validate_trip_understanding(trusted_request, proposal)
    except TripSchemaError:
        return _understanding_fallback(
            "LLM_CONTENT_INVALID", call_count, self._client.model
        )
    return TripUnderstandingGatewayResult(
        decision="MODEL_PROPOSAL",
        proposal=proposal,
        failureCode=None,
        callCount=call_count,
        model=self._client.model,
    )
```

`_understanding_fallback()` returns `decision="FIXED_QUESTIONS"` and `proposal=None`. `UnavailableTripUnderstandingGateway` validates the request and returns `LLM_NOT_CONFIGURED`, `callCount=0`, `model=None`. Never log `raw`, request JSON or validation details.

- [ ] **Step 5: Run gateway and T001/T008 compatibility tests**

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_trip_understanding_gateway.py backend/tests/test_trip_understanding_schema.py backend/tests/test_s2_t008_candidate_selection_gateway.py
```

Expected: all pass; candidate selection behavior is unchanged.

- [ ] **Step 6: Commit**

```powershell
git add app/domain/trip_draft.py app/application/llm_gateway.py backend/tests/test_s2_t004_trip_understanding_gateway.py
git commit -m "feat: add strict trip understanding gateway"
```

### Task 2: Bailian Transport and Configuration

**Files:**
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Modify: `app/infrastructure/bailian.py`
- Modify: `backend/tests/test_bailian_trip_extractor.py`
- Create: `backend/tests/test_s2_t004_bailian_transport.py`

**Interfaces:**
- Consumes: `TripUnderstandingRequest`.
- Produces: `BailianTripDraftExtractor.propose_trip_understanding(request) -> str`.
- Preserves: legacy `extract(text, reference_date)` and legacy fence acceptance only on `/api/v1` compatibility path.

- [ ] **Step 1: Write failing timeout and transport tests**

Create `backend/tests/test_s2_t004_bailian_transport.py` with the following exact tests:

| Test name | Setup | Required assertions |
|---|---|---|
| `test_trip_understanding_timeout_default_is_ten_seconds` | instantiate `Settings()` | setting equals `10.0` |
| `test_bailian_timeout_rejects_values_outside_eight_to_twelve` | parameterize 7.99 and 12.01 | both `Settings` and extractor reject each value |
| `test_understanding_request_uses_existing_openai_compatible_client` | `MockTransport` captures one success request | URL/model/temperature/response format/request JSON exact; body excludes Key and Authorization |
| `test_read_timeout_is_retryable_and_stops_after_two_attempts` | handler raises `httpx.ReadTimeout`; call through strict gateway | `LLM_TIMEOUT`, result/client/handler calls all 2 |
| `test_http_statuses_retry_only_when_transient` | parameterize 401, 403, 422, 429, 500 | failure codes and calls are `(AUTH,1)`, `(AUTH,1)`, `(UNAVAILABLE,1)`, `(UNAVAILABLE,2)`, `(UNAVAILABLE,2)` |
| `test_provider_envelope_error_is_not_retryable_or_leaked` | 200 body contains distinctive secret but no `choices` | `LLM_INVALID_RESPONSE`, one call, secret absent from logs/result |

The request test asserts model, temperature, JSON response format and that the user content equals `request.model_dump(mode="json", by_alias=True)`. It also asserts the serialized request body does not contain the test API Key or `Authorization`. The envelope error test uses a distinctive provider secret and asserts it is absent from logs/result.

- [ ] **Step 2: Run tests and observe the 45-second/missing-method failures**

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_bailian_transport.py
```

Expected: failures identify default 45 seconds, missing range enforcement and missing strict understanding method.

- [ ] **Step 3: Set the existing timeout to 10 seconds**

In `app/core/config.py`:

```python
bailian_request_timeout_seconds: float = Field(
    default=10.0,
    ge=8,
    le=12,
)
```

In `.env.example`:

```dotenv
# S2-T004 trip understanding: hard per-attempt timeout, accepted range 8..12 seconds.
BAILIAN_REQUEST_TIMEOUT_SECONDS=10
```

Do not add a second timeout setting.

- [ ] **Step 4: Add the strict raw method to the existing extractor**

In `app/infrastructure/bailian.py`, validate `8 <= timeout_seconds <= 12`, store `self.timeout_seconds`, and add:

```python
async def propose_trip_understanding(
    self,
    request: TripUnderstandingRequest,
) -> str:
    payload: dict[str, Any] = {
        "model": self.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _TRIP_UNDERSTANDING_SYSTEM_PROMPT},
            {"role": "user", "content": request.model_dump_json(by_alias=True)},
        ],
    }
    try:
        async with asyncio.timeout(self.timeout_seconds):
            response = await self._client.post(
                "/chat/completions",
                headers=self._headers,
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("message content is not text")
        return content
    except (TimeoutError, httpx.TimeoutException) as error:
        raise TripUnderstandingTransportError(
            "LLM_TIMEOUT", retryable=True
        ) from error
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in {401, 403}:
            code, retryable = "LLM_AUTH_FAILED", False
        else:
            code = "LLM_UNAVAILABLE"
            retryable = status == 429 or status >= 500
        raise TripUnderstandingTransportError(code, retryable=retryable) from error
    except httpx.TransportError as error:
        raise TripUnderstandingTransportError(
            "LLM_UNAVAILABLE", retryable=True
        ) from error
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise TripUnderstandingTransportError(
            "LLM_INVALID_RESPONSE", retryable=False
        ) from error
```

The static system prompt enumerates only T001 fields and forbids UUID/status/Constraint/Provider/Plan output. It contains no credentials or user values. This method never calls `_strip_json_fence()`; Task 1 classifies fenced content as invalid JSON.

Update legacy test constructors from `timeout_seconds=5` to `10`; do not change `test_bailian_extractor_accepts_json_code_fence` semantics.

- [ ] **Step 5: Run transport plus legacy regression**

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_bailian_transport.py backend/tests/test_bailian_trip_extractor.py backend/tests/test_trip_draft_llm_integration.py backend/tests/test_s2_t004_trip_understanding_gateway.py
```

Expected: all pass; legacy fence acceptance and strict S2 fence rejection are both observable.

- [ ] **Step 6: Commit**

```powershell
git add .env.example app/core/config.py app/infrastructure/bailian.py backend/tests/test_bailian_trip_extractor.py backend/tests/test_s2_t004_bailian_transport.py
git commit -m "feat: harden Bailian trip understanding transport"
```

### Task 3: Fixed Six-Question Fallback Projection

**Files:**
- Modify: `app/domain/collaboration.py`
- Create: `backend/tests/test_s2_t004_fixed_question_fallback.py`

**Interfaces:**
- Consumes: existing `ConversationSubmission` and frozen `QUESTION_IDS`.
- Produces: `FixedQuestionReviewItem`, `FixedQuestionFallback`, `fixed_question_fallback()`.
- Does not produce: `CollaborationIssue`, rule ID, relaxation, confirmation status or canonical field values.

- [ ] **Step 1: Write failing preservation tests**

Create `backend/tests/test_s2_t004_fixed_question_fallback.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.collaboration import (
    ConversationSubmission,
    FixedQuestionFallback,
    QUESTION_IDS,
    fixed_question_fallback,
)


def _submission() -> ConversationSubmission:
    return ConversationSubmission(
        naturalLanguageRequest="原始描述-不得改写",
        answers=[
            {"questionId": question_id, "answer": f"原答案-{index}"}
            for index, question_id in enumerate(QUESTION_IDS, start=1)
        ],
    )


def test_fixed_question_fallback_preserves_all_six_answers_in_order() -> None:
    fallback = fixed_question_fallback(_submission())

    assert fallback.mode == "FIXED_QUESTIONS"
    assert [item.question_id for item in fallback.items] == list(QUESTION_IDS)
    assert [item.answer for item in fallback.items] == [
        f"原答案-{index}" for index in range(1, 7)
    ]
    assert {item.code for item in fallback.items} == {"REVIEW_REQUIRED"}


def test_fixed_question_fallback_rejects_reordered_or_missing_items() -> None:
    valid = fixed_question_fallback(_submission())
    with pytest.raises(ValidationError):
        FixedQuestionFallback(items=list(reversed(valid.items)))
    with pytest.raises(ValidationError):
        FixedQuestionFallback(items=valid.items[:-1])


def test_fixed_question_fallback_has_no_authoritative_business_fields() -> None:
    payload = fixed_question_fallback(_submission()).model_dump(
        mode="json", by_alias=True
    )
    serialized = str(payload)
    for forbidden in (
        "tripId", "participantId", "ruleId", "relaxations",
        "confirmationStatus", "Constraint", "PlanVersion",
    ):
        assert forbidden not in serialized
```

- [ ] **Step 2: Run tests and verify the projection is absent**

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_fixed_question_fallback.py
```

Expected: collection fails on missing projection symbols.

- [ ] **Step 3: Add the minimal program-owned projection**

In `app/domain/collaboration.py`, below `ConversationSubmission`, add:

```python
class FixedQuestionReviewItem(CollaborationModel):
    question_id: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=1, max_length=1000)
    code: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    message: Literal[
        "模型未能生成可校验提案，请核对或修改此答案"
    ] = "模型未能生成可校验提案，请核对或修改此答案"


class FixedQuestionFallback(CollaborationModel):
    mode: Literal["FIXED_QUESTIONS"] = "FIXED_QUESTIONS"
    items: list[FixedQuestionReviewItem] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_fixed_question_order(self) -> "FixedQuestionFallback":
        if tuple(item.question_id for item in self.items) != QUESTION_IDS:
            raise ValueError("fallback items must contain the six fixed questions in order")
        return self


def fixed_question_fallback(
    submission: ConversationSubmission,
) -> FixedQuestionFallback:
    return FixedQuestionFallback(
        items=[
            FixedQuestionReviewItem(
                questionId=item.question_id,
                answer=item.answer,
            )
            for item in submission.answers
        ]
    )
```

Export the three public names. Do not modify `CollaborationIssue`, `IssueCode` or T003 rules.

- [ ] **Step 4: Run fixed-question and T003 contract regression**

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_fixed_question_fallback.py backend/tests/test_s2_t003_collaboration_contract.py backend/tests/test_s2_t003_revision_port.py
```

Expected: all pass; fallback remains separate from T003 issues.

- [ ] **Step 5: Commit**

```powershell
git add app/domain/collaboration.py backend/tests/test_s2_t004_fixed_question_fallback.py
git commit -m "feat: preserve fixed questions on model fallback"
```

### Task 4: T002 Wiring and Focused Regression

**Files:**
- Modify: `app/main.py`
- Modify: `app/application/trip_draft_revision_service.py` (map to T002's single landed concrete service if named differently)
- Modify: `app/api/collaboration_routes.py`
- Modify: `backend/tests/test_llm_runtime_status.py`
- Create: `backend/tests/test_s2_t004_conversation_fallback.py`

**Interfaces:**
- Consumes: Tasks 1–3, T002 answer revision/source digest/outcome store, existing T003 `TripDraftRevisionPort`.
- Produces: T002 response fields `recognition`, `understanding`, `fallback`, `canPlan`; successful proposal may enter the existing T002 canonical append.
- Idempotency: same `answerRevision + sourceDigest` returns the stored outcome; same revision/different digest fails before gateway; PENDING replay does not call the gateway.

- [ ] **Step 1: Write failing integration tests**

Create `backend/tests/test_s2_t004_conversation_fallback.py` with these exact tests:

| Test name | Setup | Required assertions |
|---|---|---|
| `test_model_failure_preserves_input_and_six_answers_without_canonical_write` | new revision, gateway returns timeout fallback | exact revision/input/answers, six review items, null understanding, false canPlan, zero canonical append |
| `test_same_answer_revision_replay_does_not_call_gateway_again` | submit identical revision/digest twice | equal outcome, gateway total calls unchanged after replay |
| `test_same_revision_with_different_source_digest_is_rejected_before_gateway` | reuse revision with changed answer | `ANSWER_REVISION_STALE`, zero new gateway calls |
| `test_new_answer_revision_is_the_only_way_to_start_a_new_call` | submit revision N, replay N, then submit N+1 | gateway called for N and N+1 only |
| `test_success_appends_only_the_strict_non_authoritative_proposal` | gateway returns strict fixture proposal | exactly one canonical append; stored object equals proposal and lacks authoritative extras |
| `test_fallback_does_not_call_workflow_constraints_plans_confirmations_or_provider` | counting fakes for every downstream | all downstream counts remain zero; only answer outcome count becomes one |
| `test_conversation_http_returns_fixed_questions_and_no_store_on_llm_failure` | call organizer conversation route twice for same revision | 200, `Cache-Control: no-store`, six items, false canPlan, no added gateway call on replay |

Use counting fakes for the gateway and every authoritative collaborator. Failure assertions:

```python
assert response.answer_revision == request.answer_revision
assert response.natural_language_request == submission.natural_language_request
assert response.answers == submission.answers
assert response.recognition.source == "FIXED_QUESTIONS"
assert response.recognition.failure_code == "LLM_TIMEOUT"
assert response.recognition.call_count == 2
assert response.understanding is None
assert response.can_plan is False
assert [item.question_id for item in response.fallback.items] == list(QUESTION_IDS)
assert canonical_revision_repository.append_count == 0
assert workflow.call_count == 0
assert provider.call_count == 0
```

Invoke the same service twice with the same revision/digest and assert the gateway count does not increase. Same revision/different payload must raise `AppError.code == "ANSWER_REVISION_STALE"` before the gateway. The HTTP test asserts status 200 and `Cache-Control: no-store`.

- [ ] **Step 2: Run tests and verify T004 is not wired yet**

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_conversation_fallback.py
```

Expected: failures identify missing gateway injection/fallback projection, not a missing second revision store.

- [ ] **Step 3: Put T002 idempotency before the gateway**

In T002's unique concrete service, use its existing repository methods in this order:

```python
claim = self.repository.claim_answer_outcome(
    draft_id=draft_id,
    participant_id=participant_id,
    answer_revision=request.answer_revision,
    source_digest=source_digest,
    idempotency_key=idempotency_key,
)
if claim.is_completed:
    return claim.outcome
if claim.is_in_progress:
    raise AppError(
        "ANSWER_REVISION_IN_PROGRESS",
        "该答案版本正在解析",
        409,
        True,
    )

gateway_result = await self.trip_understanding_gateway.understand(
    understanding_request
)
outcome = self._conversation_outcome(
    request=request,
    submission=submission,
    gateway_result=gateway_result,
)
self.repository.complete_answer_outcome(claim, outcome)
if gateway_result.decision == "MODEL_PROPOSAL":
    assert gateway_result.proposal is not None
    return self._append_canonical_revision(outcome, gateway_result.proposal)
return outcome
```

Different source digest at the same revision raises `ANSWER_REVISION_STALE` during claim. Do not hold a SQLite write transaction across the network; use T002's unique PENDING/completed outcome. Failure builds `fallback=fixed_question_fallback(submission)`, `understanding=None`, `canPlan=False` and never calls canonical append/T003 advance/workflow/Provider/confirmation stores.

- [ ] **Step 4: Wire exactly one configured client**

In `app/main.py`, add injectable `trip_understanding_gateway`. Reuse the exact managed extractor object:

```python
if trip_understanding_gateway is None:
    trip_understanding_gateway = (
        StrictTripUnderstandingGateway(managed_bailian_extractor)
        if managed_bailian_extractor is not None
        else UnavailableTripUnderstandingGateway()
    )

app.state.trip_understanding_gateway = trip_understanding_gateway
app.state.trip_draft_service = TripDraftParserService(
    service,
    llm_extractor=managed_bailian_extractor,
)
```

Inject the gateway into T002's service. Do not instantiate another `BailianTripDraftExtractor`; keep one lifespan close call.

Extend `backend/tests/test_llm_runtime_status.py` with `test_runtime_exposes_trip_understanding_gateway`, parameterized as `(None, UnavailableTripUnderstandingGateway)` and `("test-bailian-key", StrictTripUnderstandingGateway)`. The configured case asserts the gateway client is the same object used by `TripDraftParserService`; the test also verifies an injected gateway is preserved.

Configured runtime asserts the gateway client is the same object used by `TripDraftParserService`; injected gateways are preserved. Never print/assert the Key value in response or logs.

- [ ] **Step 5: Return the fallback from existing conversation routes**

In `app/api/collaboration_routes.py`, use T002's existing organizer/member service. Model degradation returns HTTP 200 data plus `Cache-Control: no-store`, because the fixed questions remain usable. Do not call `/api/v1/trips/drafts/confirm` and do not add a route.

- [ ] **Step 6: Run focused and compatibility regression**

Run the T004 slice:

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_s2_t004_trip_understanding_gateway.py backend/tests/test_s2_t004_bailian_transport.py backend/tests/test_s2_t004_fixed_question_fallback.py backend/tests/test_s2_t004_conversation_fallback.py
```

Then run compatibility tests:

```powershell
C:\Users\lenovo\Desktop\实训\2026lindashixun12zu\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q backend/tests/test_bailian_trip_extractor.py backend/tests/test_trip_draft_llm_integration.py backend/tests/test_trip_understanding_schema.py backend/tests/test_llm_runtime_status.py backend/tests/test_s2_t002_trip_draft_revision.py backend/tests/test_s2_t003_revision_port.py backend/tests/test_s2_t003_collaboration_contract.py backend/tests/test_s2_t003_collaboration_service.py backend/tests/test_s2_t003_http_boundaries.py backend/tests/test_s2_t003_readiness_guard.py backend/tests/test_s2_t008_candidate_selection_gateway.py
```

If T002's focused test file has a different landed name, replace only `backend/tests/test_s2_t002_trip_draft_revision.py` with that actual file. Expected: all pass, no collection/network errors; same answer revision adds zero model calls; fallback advances zero canonical revisions.

- [ ] **Step 7: Run hygiene checks and commit**

```powershell
git diff --check
git status --short
rg -n "logger\.(debug|info|warning|error|exception).*?(raw|prompt|answer|content|authorization|api.?key)" app/application/llm_gateway.py app/infrastructure/bailian.py
```

Expected: diff check passes; only intended T004 files are modified; logger scan has zero sensitive-payload log calls.

```powershell
git add app/main.py app/application/trip_draft_revision_service.py app/api/collaboration_routes.py backend/tests/test_llm_runtime_status.py backend/tests/test_s2_t004_conversation_fallback.py
git commit -m "feat: degrade conversation understanding to fixed questions"
```

If T002 service path differs, stage that existing file instead of the example path; never stage a duplicate service.

## Final Verification and Handoff

- [ ] `git status --short` is empty.
- [ ] Record exact focused and compatibility test counts.
- [ ] Record the four task commit SHAs.
- [ ] Report worst-case model wait as two 10-second attempts, not one 20-second request.
- [ ] Report same answer revision replay adds zero model calls and fallback advances zero canonical revisions.
- [ ] Report no UI, duplicate client/store, Provider, Trip, Constraint, PlanVersion, workflow, confirmation-state or old S1 behavior change.
