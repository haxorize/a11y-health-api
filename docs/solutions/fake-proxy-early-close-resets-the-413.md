---
title: "A test server that answers early and closes resets the connection before the client reads the answer"
problem_type: test_failure
tags: [cli, live-server, fake-proxy, socket, tcp-reset, flake, httpx, uvicorn]
symptoms:
  - "a11y_health.cli._client.ApiUnreachableError: Could not reach the API at http://127.0.0.1"
  - "httpcore.ReadError raised in _receive_response_body"
  - "test_large_post_rejected_by_a_proxy_is_one_failed_page_and_the_run_continues failed once in the pre-commit hook and passes when run alone"
  - "a 413 or other early response never reaches the client; it reports the server unreachable instead"
root_cause: "The fake proxy answered a large POST and closed without reading the body, so body bytes arriving after the close made the kernel reset the connection, and the reset destroyed the unread response"
module: tests/cli
date: 2026-10-18
---

# A test server that answers early and closes resets the connection before the client reads the answer

## Problem

The CLI's live-server tests run the app under uvicorn behind `_FakeProxy`, a fake reverse proxy in `tests/cli/conftest.py` whose behavior each request picks with the `x-test-proxy` header. Its `body-limit` behavior models an ingress with a request-size cap: a POST over 4096 bytes gets an HTML 413 and a closed connection. `test_large_post_rejected_by_a_proxy_is_one_failed_page_and_the_run_continues` in `tests/cli/test_live_server.py` asserts that the CLI reports that 413. It failed once in the pre-commit hook with `ApiUnreachableError` instead.

The chained traceback showed `httpcore.ReadError` inside `_receive_response_body`, so the client had read the 413's status line and lost the connection before the body. The `body-limit` branch sent its 413 with `connection: close` and returned without reading the request body. When body bytes reached the server after uvicorn closed the socket, the kernel answered them with a TCP reset. The reset discarded the part of the 413 that was still unread in the client's receive buffer.

The 413 can be unread at that moment because of how the client reads. httpcore writes the whole request before it reads the response, and anyio reads from the socket only while a `receive()` is waiting. So the 413 waits in the kernel buffer until the body is written. The failure is still rare, because on loopback the body almost always reaches the server before it closes, and then no reset is sent.

## What didn't work

- **Repeating the test.** The test file passed 30 runs in a row, and the full suite passed 12. The test file also passed 40 runs with 8 parallel copies and 8 CPU-burning processes. Ordinary load does not open the window, because the body still lands before the close.
- **Pausing between the response headers and body.** A client that paused after reading the 413's headers never failed in 50 tries. The reset needs request bytes that arrive after the close. uvicorn had already read every byte that arrived earlier, so nothing was left to trigger it.
- **A bigger body or a longer pause.** These did not raise the failure rate. A 100,000-byte body failed 1 upload in 50, and a 200 ms pause failed 5 in 30, against 1 to 8 in 50 at 10,000 bytes and 50 ms. The rate depends on how the kernel orders the reset against the client's read, which no timeout controls.

The loop that worked held part of the request body back until after the server's close. It used an async generator body that yields 1024 bytes, sleeps 50 ms, yields the rest, and sleeps again. Through the suite's own `_FakeProxy`, it failed 17 of 200 uploads with `ReadError`.

## Fix

The `body-limit` branch now reads and discards the request body between sending the 413's headers and sending its final body message. uvicorn closes the connection when that final message goes out, so the close comes after the whole body has been read. Real reverse proxies avoid the same reset in the same way: after rejecting a request, they keep reading and discarding its body for a short time before closing, which nginx calls a lingering close. With nothing left to arrive after the close, the kernel has no reason to send a reset. The loop above went from 17 failures in 200 to 0 in 200, and back to 16 in 200 with the drain reverted.

## Prevention

`test_the_body_limit_proxy_reads_the_whole_body_before_its_413_completes` calls `_FakeProxy` directly, with no socket, using a request body in 2 chunks. It asserts that no chunk is unread when the final response message goes out. The test does not depend on timing, so it fails on every run if the drain is removed. Any new fake-server behavior that answers before the request is fully read and then closes needs the same drain, or an equivalent test. #140 describes one such behavior: a proxy that closes the connection partway through reading the body.
