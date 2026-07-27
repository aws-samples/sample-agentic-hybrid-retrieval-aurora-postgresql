# References for release authors

Official AWS documentation should be rechecked before the event.

## AgentCore Gateway

- Gateway overview:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
- OpenAPI targets:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-schema-openapi.html
- Gateway setup:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building.html
- Target configuration:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html

Key release checks:

- supported OpenAPI version;
- `operationId` behavior;
- supported schema features;
- target auth;
- MCP endpoint invocation;
- quotas and Region availability.

## Aurora PostgreSQL depth (§18)

- Optimized Reads, tiered cache, and the `aurora_orcache_hit` / `aurora_storage_read`
  buffer counters:
  https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.optimized.reads.html
- Optimized Reads with pgvector, including the BIGANN-1B benchmark quoted in §18.3:
  https://aws.amazon.com/blogs/database/accelerate-generative-ai-workloads-on-amazon-aurora-with-optimized-reads-and-pgvector/
- Aurora PostgreSQL wait events:
  https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.Reference.Waitevents.html

Key release checks:

- `aurora_stat_plans` availability and column set on the target engine version;
- `aurora_compute_plan_id` and `aurora_stat_plans.with_buffers` in the parameter group;
- whether the cluster is Aurora I/O-Optimized — the tiered cache does not exist on
  Aurora Standard, and its absence is silent;
- benchmark figures still current, or removed from the material.

## CloudWatch Database Insights

- Execution plans:
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Database-Insights-Execution-Plans.html
- Lock analysis:
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Database-Insights-Lock-Analysis.html
- Aurora plan capture:
  https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.Monitoring.Query.Plans.html

Key release checks:

- Advanced mode;
- `aurora_compute_plan_id`;
- estimated versus actual plan label;
- `aurora_stat_plans.with_analyze`;
- lock-tree availability for the demo window.
