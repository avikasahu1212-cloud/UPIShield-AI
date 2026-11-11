# UPIShield - Assumptions Document

This document records every assumption made during the development of UPIShield.

## Data Assumptions

### Propagation Probabilities
- **hard = 0.8**: When a hard dependency fails, there's an 80% chance the dependent node is affected. This is based on the assumption that critical payment routing failures propagate with high probability.
- **soft = 0.35**: When a soft dependency degrades, there's a 35% chance the dependent node is affected. This reflects partial or non-critical dependencies.
- **retry_sensitive soft = 0.65**: Soft dependencies that are retry-sensitive have a higher propagation probability because retries amplify the load.

### Incident Magnitudes
- **bank_slowdown**: Latency increases 3.6x, timeouts reach 5%, success rate drops to 62%. These are assumed severe degradation levels.
- **retry_storm**: Requests triple, latency 4x, timeouts reach 8%, success drops to 50%. Assumes a feedback loop of retries overwhelming the system.
- **shared_upstream**: Cloud region failure affects bank_b, bank_c, and payment_gateway_1 with 1-2 minute stagger. Assumes shared infrastructure dependency.
- **gradual_degradation**: Latency ramps to 2.5x over 45 minutes, timeouts to 2%, success to 94%. Represents a slow-moving issue.
- **mild_incident**: Latency 1.6x, timeouts 1.2%, success 96%. A minor issue that should not trigger alerts.
- **benign_peak**: Volume increases 1.6x, latency up at most 10%. Represents normal traffic spikes.

### Traffic Patterns
- Base rate: 500 requests/second for NPCI switch (assumed from typical UPI volumes).
- Two daily peaks at 11:00 and 19:00 with 2.5x multiplier (assumed from Indian payment patterns).
- Trough at 02:00-05:00 with 0.3x multiplier.
- Weekend factor: 0.85 (assumed 15% reduction).
- Salary day bump: 1.1x on the 5th of each month (simplified assumption).

### Baseline Metrics
- p95 latency: 40-250ms depending on node type. Banks have higher latency (150-240ms), cloud services lower (40-100ms).
- Timeout ratio: ~0.4% under normal conditions.
- Success rate: ~98.5% under normal conditions.
- Retry ratio: 2-4% under normal conditions.
- Pending transactions: ~0.2% of requests.

## ML Model Assumptions

### Isolation Forest
- One model per node (12 models total).
- 200 estimators per model.
- Scores calibrated via empirical CDF of training scores.
- Alert threshold: default 99.5th percentile of training scores (tuned on validation split).

### Alert Persistence
- Alert fires when 3 of the last 5 windows exceed the threshold.
- Alert resolves after 5 consecutive normal windows.
- These parameters are tuned on the validation split.

## Graph Assumptions

### Topology
- 12 nodes representing a simplified UPI payment chain.
- Edge direction: A->B means "A depends on B". A failure at B can propagate to A.
- 19 edges representing various dependency types.

### Cascade Simulation
- Independent cascade model: each node gets exactly one attempt per outgoing edge.
- Delay sampled from exponential distribution with mean = delay_min_mean.
- Min-heap tracks earliest failure time per node.
- 5000 trials by default (configurable 100-50000).

### RCA Scoring
- Weights: earliness 0.35, explained_fraction 0.35, normalised_peak_score 0.20, victim_penalty 0.30.
- Correlation window: 10 minutes.
- Victim penalty penalizes nodes whose dependencies are anomalous earlier (indicating they may be victims, not roots).

## Infrastructure Assumptions

### Kafka
- Single node, single partition (global time order preserved).
- Production would partition by node_id or region.
- Ingest mode defaults to "file" (ReplaySource); Kafka requires Docker.

### Neo4j
- Community edition used.
- GraphStore protocol allows swapping implementations.
- Default is NetworkX in-memory for file mode; Neo4j for Kafka mode.

### Monitoring
- SQLite with WAL mode for runtime data.
- Prometheus exposition format at /metrics.
- Prometheus + Grafana are optional (docker compose profile "monitoring").

## Evaluation Assumptions

- **All data is synthetic.** No real bank or transaction data is used.
- The generator uses the same propagation probabilities as the cascade engine, so validating cascade predictions against this data would be circular.
- Evaluation results validate the pipeline on synthetic data, not real-world accuracy.
- The split is: train (days 1-4), validation (day 5), test (days 6-7).
- shared_upstream appears ONLY in the test split and is never used for tuning.

## Out of Scope
- LLM/Ollama integration
- Recommendations engine
- Approval workflow
- Recovery execution
- Verification
- PDF reports
- React dashboard
- Real bank data integration