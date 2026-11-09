# Search call timeouts, measured 9 November 2026

On the 9 November test event of release `e202e18f6049c475`, search `a9ae417b` (Lab 1's
handoff) spent 60,966 ms in its Amazon Bedrock reranking call while retrieval took 59 ms. The
call never answered. The shared Bedrock client waits 60 s for a response
(`read_timeout=60`, `BEDROCK_MAX_ATTEMPTS=5`, adaptive retries), so the participant's
command sat silent for a minute before the retry answered.

Source `1fd1ff0b` gives a search's two Bedrock calls, the query embedding and reranking,
their own clients that wait 10 s per attempt (`SEARCH_READ_TIMEOUT_SECONDS` in
`service/bedrock.py`), with the same attempts and backoff. Model calls (the agent, the cited
answer, the claim review) and catalog embedding batches keep 60 s. When no attempt answers,
the search stops with HTTP 503 and this sentence, which the lab commands print after
`/api/search returned HTTP 503:` and the Shop shows as the request's error:

> This search stopped: Amazon Bedrock's reranking call did not answer within 10 seconds,
> even after retrying. Nothing is wrong with your work. Run the same command or search again.

The query embedding's version names the `embedding call`.

## How long a search's Bedrock calls take

Every search the development cluster recorded (`mosaic.search_event`, the
`stage_timings_ms` in each row's diagnostics), 26 September to 9 November 2026:

| Call | Searches | Median | 95th percentile | 99th percentile | 99.9th percentile | Longest | Over 10 s |
|---|---|---|---|---|---|---|---|
| Query embedding | 2,450 | 0 ms (cached) | 428 ms | 719 ms | 2,516 ms | 10,700 ms | 1 |
| Reranking | 2,443 | 817 ms | 1,954 ms | 6,309 ms | 15,685 ms | 19,631 ms | 11 |

No call took 30 s or more, so the development cluster never saw the event's hang. Of the 33
reranking calls over 5 s, 26 came on the morning of 22 October during concurrent agent runs,
22 of them between 09:53 and 09:55 UTC, when each had 14 searches within a minute either side
and the calls around it had a median of 4.7 s, against about 1 s otherwise. Nine of the 11
calls over 10 s were in those two minutes; the other two were concurrent searches on
19 October.

So a 10 s wait per attempt cuts a slow call about once in 220 searches, almost all under
concurrent load. The attempts stay at five: a cut attempt is retried, which under load costs
about what waiting would, and throttled calls keep the retries they had. The cost is the
outage case, where every attempt goes unanswered: about 60 s before the sentence, against
about 5 minutes before.

## Reproduction

A search on the production path (`service.main.search`: Aurora candidates, a real Bedrock
query embedding, reranking, telemetry and the route's error mapping) from a laptop against
the development cluster (Aurora PostgreSQL 18.6, pgvector 0.8.2), with
`bedrock-agent-runtime` pointed at a local endpoint. That endpoint holds a request without
answering, or returns valid scores for every candidate. Laptop-to-Region latency inflates the
other stages; the reranking stage is the comparable number.

| Case | Source | Reranking requests (s after start) | Result | Reranking stage |
|---|---|---|---|---|
| First request held, retry answered (the event's case) | `218eb9cf`, before | 8.1, 68.7 | HTTP 200 | 60,600 ms |
| First request held, retry answered | `1fd1ff0b`, after | 6.9, 16.9 | HTTP 200 | 10,015 ms |
| Every request held | `218eb9cf`, before | 7.0, 67.6, 128.1, 188.9, 252.1 | HTTP 503 after 315 s: "Amazon Bedrock request failed. Retry after checking model access and region." | |
| Every request held | `1fd1ff0b`, after | 7.1, 17.5, 27.7, 40.3, 58.1 | HTTP 503 after 68 s: the sentence above | |

`tests/test_bedrock_search_timeouts.py` holds the same behavior offline: a local endpoint that
never answers stops both the reranking and the embedding call with the sentence after two
0.3 s attempts, the classifier passes the sentence through, the search route returns it as the
503 detail, and the lab commands print it instead of the JSON body. Each of the eight tests
failed when its part of the change was reverted (reranking or embedding on the model client,
the classifier without the pass-through, the raw body printed, the wait back at 60 s).

## Not proven here

- A real unanswered Bedrock call on an event: it cannot be caused on demand. The next test
  event shows that searches still answer and Lab 1's handoff takes its usual time.
- What a participant reads when the Retrieval agent's own search stops on AgentCore Runtime.
  The agent ends the run on this error as on any Bedrock failure (`_stopping_error` in
  `service/agent_tools.py`), and `service/agentcore_transport.py` notes that Runtime passes
  back the status without the agent's explanation, so `ask_agent.py` likely prints its own
  failure line instead of this sentence. Not observed.
