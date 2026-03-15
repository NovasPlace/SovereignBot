"""Architectural Engineering Skillset.

System-level thinking. Designs distributed systems, evaluates trade-offs
across reliability/performance/cost/complexity, and thinks in failure
domains, data flow, and operational reality.
"""

MANIFEST = {
    "name": "architectural_engineering",
    "display_name": "Architectural Engineering",
    "trust_tier": "CORE",
    "triggers": [
        "architect", "system design", "infrastructure", "distributed",
        "microservice", "monolith", "scale", "availability", "consistency",
        "cap", "database choice", "message queue", "event-driven",
        "topology", "failover", "disaster recovery", "multi-region",
        "containerize", "kubernetes", "service mesh", "load balancer",
        "high availability", "fault tolerance",
    ],
    "memory_bias": {
        "preferred_tags": [
            "architecture", "infrastructure", "system-design", "scaling",
            "reliability", "post-mortem", "deployment", "networking",
        ],
        "emotion_bias": "curiosity",
    },
}

REASONING_FRAMEWORK = (
    "## Architectural Engineering Reasoning Framework\n\n"
    "### First Principles — Ask Before Designing\n"
    "1. What are the actual requirements? (not what someone thinks they want)\n"
    "2. Read/write ratio? Data volume?\n"
    "3. Consistency requirement? (strong, eventual, causal?)\n"
    "4. Latency budget? (p50, p95, p99)\n"
    "5. Availability target? (three 9s? five 9s?)\n"
    "6. Who operates this? What's their on-call look like?\n"
    "7. What's the budget?\n\n"
    "### Architecture Evaluation (6 dimensions)\n"
    "| Dimension    | Key Question                                    |\n"
    "|-------------|------------------------------------------------|\n"
    "| Reliability  | What fails? Single point of failure? Blast radius? |\n"
    "| Performance  | Latency path? Bottlenecks? Ceiling?             |\n"
    "| Scalability  | What breaks at 10x? 100x? Where's the cliff?   |\n"
    "| Operability  | Can someone debug this at 3am with a pager?     |\n"
    "| Cost         | Cost at current scale? At 10x?                  |\n"
    "| Simplicity   | Can a new engineer understand this in a week?    |\n\n"
    "### Failure Mode Analysis (MANDATORY)\n"
    "- List every component that can fail\n"
    "- For each: detection time, recovery time, data loss?\n"
    "- Map the dependency graph — what cascades?\n"
    "- Design circuit breakers BEFORE they're needed\n\n"
    "### Common Patterns (use the right one)\n"
    "- Event sourcing: when audit trail matters\n"
    "- CQRS: when read/write models differ fundamentally\n"
    "- Saga: distributed transactions across services\n"
    "- Circuit breaker: unreliable external dependencies\n"
    "- Bulkhead: failure isolation between subsystems\n"
    "- Strangler fig: incremental monolith migration\n\n"
    "### Anti-Patterns to Flag\n"
    "- Distributed monolith (can't deploy independently)\n"
    "- Shared database between services\n"
    "- Synchronous chains > 3 hops\n"
    "- No backpressure\n"
    "- Resume-driven architecture (K8s for 100 req/s)\n\n"
    "### Output Format\n"
    "1. Context and constraints\n"
    "2. Topology diagram\n"
    "3. Data flow (write, read, failure paths)\n"
    "4. Component inventory with failure modes\n"
    "5. Trade-offs and rejected alternatives\n"
    "6. Operational requirements\n"
    "7. Cost at current and 10x scale"
)
