# UPIShield Data Card

## What is Synthetic

**ALL data in this project is synthetic.** There is no real bank data, no real transaction data, and no real operational data from any payment system. All node identifiers (bank_a, bank_b, etc.) are generic placeholders. All metrics are generated using statistical models calibrated to plausible but fictional UPI traffic patterns.

**This data validates the pipeline, not real-world accuracy.** The generator uses the same propagation probabilities as the cascade engine, so validating cascade predictions against this data would be circular.

## Baselines

Baseline metrics for each node are documented in `app/config.py:BASELINES`. Key values:
- **p95 latency**: 40-250 ms depending on node type (cloud lowest, banks highest)
- **timeout_ratio**: ~0.004 (0.4%)
- **success_rate**: ~0.985 (98.5%)
- **retry_ratio**: 0.02-0.04 (2-4%)
- **pending_txns**: ~0.2% of requests

## Scenario Definitions

| Scenario | Root Node | Effect | Severity |
|----------|-----------|--------|----------|
| bank_slowdown | bank_a/b/c | Latency x3.6, timeouts to 0.05, success to 0.62 | High |
| retry_storm | status_check_api | Requests x3, latency x4, timeouts 0.08, success 0.5 | High |
| shared_upstream | cloud_region_1 | bank_b, bank_c, payment_gateway_1 degrade 1-2 min apart | High |
| gradual_degradation | bank_a/b/c | Latency ramps to x2.5 over 45 min, timeouts to 0.02 | Medium |
| mild_incident | bank_a/b/c | Latency x1.6, timeouts 0.012, success 0.96 | Low |
| benign_peak | none | Volume x1.6, latency up at most 10%, timeouts x1.2 | None (not an incident) |

## Data Split

| Split | Days | Incidents |
|-------|------|-----------|
| Train | Days 1-4 | 1 benign_peak, 2 mild_incident |
| Validation | Day 5 | 1 bank_slowdown, 1 retry_storm, 1 gradual_degradation, 1 benign_peak |
| Test | Days 6-7 | 2 bank_slowdown, 1 retry_storm, 1 gradual_degradation, 2 shared_upstream, 2 mild_incident, 1 benign_peak |

**Note**: `shared_upstream` appears ONLY in the test split. It is never used for tuning.

## Assumptions

1. Propagation probabilities (0.8 hard, 0.35 soft) are assumptions, not measured values.
2. Incident magnitudes (latency multipliers, timeout targets) are assumptions.
3. Traffic shape (daily peaks, weekend factor) is based on general UPI patterns but not from any specific production system.
4. The generator uses exponential delays for incident propagation, which may not match real-world propagation patterns.
