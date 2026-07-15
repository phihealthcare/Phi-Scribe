from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from app.services.pipeline_tracker import PipelineTracker

DEFAULT_LLM_BASE_URL = "https://api.phihc.com"
DEFAULT_LLM_PATH = "/api/medgemma"

# Guards against a stuck/degenerate generation (observed: model looped on a
# repeated token pattern for 837s and 245KB before the response ever stopped).
# urllib's `timeout` only bounds each individual socket read, not the total
# request duration — as long as the server keeps streaming SOMETHING, no
# single read ever blocks long enough to trip it. Both checks below enforce
# a real wall-clock/size ceiling regardless of how the bytes trickle in.
MAX_LLM_RESPONSE_BYTES = 200_000
_READ_CHUNK_SIZE = 65536


def _read_response_with_deadline(response: Any, *, deadline_s: float, max_bytes: int) -> bytes:
    started = time.monotonic()
    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() - started > deadline_s:
            raise TimeoutError(
                f"LLM response streaming exceeded {deadline_s:.0f}s wall-clock deadline "
                f"({total} bytes received so far)"
            )
        chunk = response.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError(
                f"LLM response exceeded {max_bytes} bytes without completing — "
                "likely a runaway/degenerate generation, aborting"
            )
    return b"".join(chunks)


def llm_endpoint_url(base_url: str, *, path: str = DEFAULT_LLM_PATH) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith(DEFAULT_LLM_PATH):
        return base
    if path.startswith("/"):
        return f"{base}{path}"
    return f"{base}/{path}"


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:\w+)?\s*\n?(.*?)\n?```\s*$", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def estimate_max_tokens(text: str, *, minimum: int = 1024, multiplier: int = 3) -> int:
    word_count = len(text.split())
    return max(minimum, word_count * multiplier)


def _normalize_api_key(raw: Any) -> str:
    key = str(raw or "").strip()
    if not key or key.lower() in {"null", "none", "local"}:
        return ""
    return key


def _resolve_int_config(config: Mapping[str, Any], name: str, default: int) -> int:
    raw = config.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def resolve_llm_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    base_url = str(config.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)).strip().rstrip("/")
    if not base_url:
        raise ValueError("LLM_BASE_URL is required")

    api_key = _normalize_api_key(config.get("LLM_API_KEY"))
    default_timeout = _resolve_int_config(config, "LLM_TIMEOUT_SECONDS", 600)
    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": str(config.get("TRANSCRIPT_POSTPROCESS_MODEL", "gemma3:12b-it-qat")),
        "provider": str(config.get("TRANSCRIPT_POSTPROCESS_PROVIDER", "phihc")),
        "timeout": default_timeout,
        "asr_fix_timeout": _resolve_int_config(config, "LLM_ASR_FIX_TIMEOUT_SECONDS", 900),
        "asr_fix_max_retries": _resolve_int_config(config, "LLM_ASR_FIX_MAX_RETRIES", 2),
        "soap_max_retries": _resolve_int_config(config, "LLM_SOAP_MAX_RETRIES", 0),
    }


def _split_messages(messages: list[dict[str, str]]) -> tuple[str, str]:
    system_prompt = ""
    user_parts: list[str] = []
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            system_prompt = content
        else:
            user_parts.append(content)
    return system_prompt, "\n\n".join(user_parts)


def _extract_response_text(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()

    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected LLM response type: {type(data).__name__}")

    for key in ("response", "text", "content", "output", "result"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
            text = first.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()

    raise RuntimeError(f"Unexpected LLM response shape: {sorted(data.keys())}")


def _is_retryable_llm_error(message: str) -> bool:
    return any(token in message for token in ("HTTP 502", "HTTP 503", "HTTP 429"))


def medgemma_generate(
    *,
    prompt: str,
    system_prompt: str = "",
    model: str = "gemma3:12b-it-qat",
    base_url: str = DEFAULT_LLM_BASE_URL,
    api_key: str,
    temperature: float = 0,
    force_json: bool = False,
    timeout: int = 600,
    max_retries: int = 0,
    return_raw: bool = False,
    tracker: PipelineTracker | None = None,
    tracker_step_id: str | None = None,
    tracker_record_step: bool = True,
    tracker_request_meta: dict[str, Any] | None = None,
) -> str | tuple[str, str]:
    """Call PhiHC MedGemma (Gemma via Ollama) at POST /api/medgemma."""
    normalized_key = _normalize_api_key(api_key)
    if not normalized_key:
        raise ValueError("LLM_API_KEY is required for PhiHC MedGemma API")

    user_prompt = prompt.strip()
    if not user_prompt:
        raise ValueError("LLM prompt is empty")

    payload = {
        "prompt": user_prompt,
        "system_prompt": system_prompt.strip(),
        "model": model,
        "temperature": temperature,
        "force_json": force_json,
    }

    url = llm_endpoint_url(base_url)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {normalized_key}",
        },
    )

    log_request = {
        "url": url,
        "model": model,
        "temperature": temperature,
        "force_json": force_json,
        "timeout_seconds": timeout,
        "system_prompt": payload["system_prompt"],
        "prompt": user_prompt,
    }
    if tracker_request_meta:
        log_request.update(tracker_request_meta)

    def _append_exchange(
        *,
        response: Any = None,
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        if not tracker:
            return
        tracker.append_llm_request(
            step_id=tracker_step_id,
            request=log_request,
            response=response,
            error=error,
            duration_ms=duration_ms,
            meta=tracker_request_meta,
        )

    def _fail_request(error_message: str, *, exc: BaseException | None = None) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        _append_exchange(error=error_message, duration_ms=duration_ms)
        if tracker and tracker_step_id and tracker_record_step:
            tracker.record(
                tracker_step_id,
                request=log_request,
                error=error_message,
                duration_ms=duration_ms,
            )
        raise RuntimeError(error_message) from exc

    attempts = max(1, max_retries + 1)
    raw = ""
    started = time.perf_counter()
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_bytes = _read_response_with_deadline(
                    response, deadline_s=timeout, max_bytes=MAX_LLM_RESPONSE_BYTES
                )
            raw = raw_bytes.decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            error_message = f"LLM HTTP {exc.code}: {detail[:500]}"
            if attempt < attempts - 1 and _is_retryable_llm_error(error_message):
                _append_exchange(error=error_message, duration_ms=(time.perf_counter() - started) * 1000)
                time.sleep(min(3.0, 0.75 * (attempt + 1)))
                continue
            _fail_request(error_message, exc=exc)
        except urllib.error.URLError as exc:
            error_message = f"LLM request failed: {exc.reason}"
            if attempt < attempts - 1 and _is_retryable_llm_error(error_message):
                _append_exchange(error=error_message, duration_ms=(time.perf_counter() - started) * 1000)
                time.sleep(min(3.0, 0.75 * (attempt + 1)))
                continue
            _fail_request(error_message, exc=exc)
        except TimeoutError as exc:
            message = str(exc).strip() or "The read operation timed out"
            _fail_request(message, exc=exc)
        except RuntimeError as exc:
            _fail_request(str(exc), exc=exc)
        except OSError as exc:
            message = str(exc).strip() or type(exc).__name__
            _fail_request(message, exc=exc)

    duration_ms = (time.perf_counter() - started) * 1000

    if not raw.strip():
        error_message = "LLM returned empty body"
        _append_exchange(error=error_message, duration_ms=duration_ms)
        if tracker and tracker_step_id and tracker_record_step:
            tracker.record(
                tracker_step_id,
                request=log_request,
                error=error_message,
                duration_ms=duration_ms,
            )
        raise RuntimeError(error_message)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        text = strip_markdown_fences(raw)
        response_payload = {"raw": raw, "text": text}
        _append_exchange(response=response_payload, duration_ms=duration_ms)
        if tracker and tracker_step_id and tracker_record_step:
            tracker.record(
                tracker_step_id,
                request=log_request,
                response=response_payload,
                duration_ms=duration_ms,
            )
        return (text, raw) if return_raw else text

    content = _extract_response_text(parsed)
    if not content:
        error_message = "LLM returned empty content"
        _append_exchange(response={"raw": raw}, error=error_message, duration_ms=duration_ms)
        if tracker and tracker_step_id and tracker_record_step:
            tracker.record(
                tracker_step_id,
                request=log_request,
                response={"raw": raw},
                error=error_message,
                duration_ms=duration_ms,
            )
        raise RuntimeError(error_message)
    text = strip_markdown_fences(content)
    response_payload = {"raw": raw, "text": text}
    _append_exchange(response=response_payload, duration_ms=duration_ms)
    if tracker and tracker_step_id:
        tracker.record(
            tracker_step_id,
            request=log_request,
            response=response_payload,
            duration_ms=duration_ms,
        )
    return (text, raw) if return_raw else text


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str,
    base_url: str,
    api_key: str,
    max_tokens: int,
    temperature: float = 0,
    json_mode: bool = False,
) -> str:
    del max_tokens  # MedGemma endpoint does not accept max_tokens.

    system_prompt, prompt = _split_messages(messages)
    return medgemma_generate(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        force_json=json_mode,
    )
