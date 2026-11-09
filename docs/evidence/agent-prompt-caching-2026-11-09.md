# Agent prompt caching, measured 9 November 2026

Mosaic turns on Amazon Bedrock prompt caching in two places:

- **The Retrieval agent's loop.** `service/agent.py` builds its Strands `BedrockModel` with
  `cache_config=CacheConfig(strategy="auto")` (Strands 1.48.0). A cache point closes each
  round's latest message, so the next round reads the instructions, tool definitions and
  earlier tool results from the cache.
- **The cited-answer step.** `service/synthesis.py` sends its fixed system prompt (7,389
  characters, 2,179 tokens) with a cache point after it, through `cached_system` in
  `service/bedrock.py`. Only Claude model IDs get the cache point.

Each run record now keeps `cache_read_input_tokens` and `cache_write_input_tokens` beside
`input_tokens` (`strands` usage), and the cited answer's Bedrock usage keeps
`cacheReadInputTokens` and `cacheWriteInputTokens`.

## How it was measured

A Workshop Studio test event account (us-east-1, Aurora PostgreSQL 18.6, both runtimes on
`platformVersion` V1), with this change on the host. `lab_state.py skip-to --lab 3`, the
reference Retrieval agent, `deploy_agentcore.py deploy` (Retrieval agent runtime version 3),
then Alex's setup request three times and the 100W follow-up three times with
`scripts/ask_agent.py`. Tokens were read from `mosaic.agent_turn`. Model:
`global.anthropic.claude-sonnet-5-5`.

| Asked (UTC) | Request | Agent: uncached input | Agent: cache read | Agent: cache write | Cycles | Cited answer: cache read / write | Answer drafts |
|---|---|---|---|---|---|---|---|
| 13:49:49 | Setup | 12 | 77,995 | 42,787 | 5 | 0 / 2,179 | 1 |
| 13:50:26 | Setup | 12 | 71,224 | 35,714 | 5 | 4,358 / 0 | 2 |
| 13:51:20 | Setup | 10 | 55,121 | 39,008 | 4 | 4,358 / 0 | 2 |
| 13:53:19 | 100W | 10 | 32,499 | 23,547 | 4 | 4,358 / 0 | 2 |
| 13:53:58 | 100W | 14 | 79,640 | 20,303 | 6 | 2,179 / 0 | 1 |
| 13:54:53 | 100W | 10 | 36,225 | 19,793 | 4 | 2,179 / 0 | 1 |

All three follow-ups answered `grounded` (39, 55 and 32 s), and `grade_setup_run.py` printed
`Lab 3 exercise: PASS`.

## What it saves

Prices, Claude Sonnet 5.5 through global cross-Region inference, us-east-1, 6 November 2026,
per million tokens: input $2.00, cache read $0.10, five-minute cache write $2.50. The same
prompts without caching would bill every cached token as input.

| Request | Input cost without caching | With caching | Less |
|---|---|---|---|
| Setup, three turns | $0.3136, $0.3493, $0.3230 | $0.1879, $0.2235, $0.2295 | 40%, 36%, 29% |
| 100W, three turns | $0.1637, $0.2325, $0.1443 | $0.1054, $0.0872, $0.0812 | 36%, 63%, 44% |
| All six | $1.5264 | $0.9148 | 40% |

Output tokens are unchanged by caching and not included. Six turns on one account are a
sample, not a distribution: measure your own turns from the run record.
