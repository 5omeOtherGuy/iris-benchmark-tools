---
name: benchmark-telemetry-report
description: Produce rigorous, evidence-backed coding-agent benchmark reports from raw telemetry, including controlled harness comparisons, token/cache/cost decomposition, timing, failure and outlier forensics, actionable recommendations, and polished self-contained HTML. Use when asked to analyze benchmark runs, compare harness efficiency, explain cost/cache/latency behavior, inspect anomalous turns or failures, correct an earlier benchmark verdict, or publish a readable telemetry report.
user-invocable: true
---

# Benchmark telemetry report

Turn preserved benchmark telemetry into a reproducible analysis and a decision-quality report. Prefer measured, controlled conclusions over headline totals.

This skill owns analysis and presentation. It does not redefine source schemas or benchmark execution:

- Use `harness-telemetry` as the data contract.
- Use `harness-benchmark` for run methodology and benchmark hygiene.
- Reuse the repository's `analyze_tokens.py` and its parsers before writing new accounting logic.
- Read the benchmark archive log, when one exists, for prior-run context and stale conclusions that may need correction.

Do not rerun a benchmark unless the user asks or the preserved evidence cannot answer the question.

## Deliverables

Unless the user narrows the request, produce:

1. A reproducible trial-level dataset and analysis script or command.
2. A Markdown source report.
3. A self-contained HTML report with the full analysis, not a summary-only dashboard.
4. A short user-facing verdict linking the report and evidence artifacts.
5. A corrected archive-log entry when the analysis materially changes a recorded verdict.

Store benchmark data and generated artifacts in the configured private benchmark directory, never in tracked source. A user-requested copy of a final sanitized report may be placed elsewhere.

## Analysis workflow

### 1. Establish the comparison

Record before calculating:

- job and trial directories;
- contenders, exact versions/commits, provider, and model;
- dataset and commit;
- tasks, attempts `k`, task order, concurrency, and run order;
- cache policy and pricing date;
- authentication/account sharing, rate-limit events, and environment differences;
- whether the design is controlled (same model) or product-level (model confounded).

Match tasks and attempts explicitly. Never compare aggregates from different task sets without labeling the mismatch.

### 2. Validate the raw telemetry

Read actual files before making claims. Run structural checks before analysis.

For Iris:

- Verify `fresh + cache_read + cache_write == input_full` per turn.
- Treat `turns[]` as flows and `latest_total_tokens` as a level; never sum snapshots.
- Treat `base.*` as local tokenizer estimates, not provider truth.
- Keep 5-minute and 1-hour cache writes separate.
- Use session JSONL for complete tool history and active timing.

For Claude Code:

- Deduplicate stream usage by message ID.
- Use ATIF `final_metrics.total_completion_tokens` and per-step completion tokens; stream output can omit hidden reasoning.
- Treat stream `input_tokens` as fresh input only.
- Do not trust trajectory timestamps for trial timing.

Across harnesses:

- Use trial-directory mtime spans for uniform end-to-end timing unless a newer, validated common source exists.
- Reconcile totals against per-turn data.
- Distinguish zero, missing, unsupported, and unknown.
- Surface parser warnings; do not silently coerce malformed data.

Stop and explain if identities fail or source semantics are unresolved.

### 3. Build one canonical trial table

Include at least:

- harness, task, attempt/trial ID, success/reward, and termination class;
- provider turns and tool calls by name;
- fresh input, cache reads, cache writes by TTL, full input, output, and reasoning when known;
- observed cost, cold-normalized product-policy cost, and equal-TTL cost;
- provider-observed fixed prefix, task-prompt suffix, and dynamic input area;
- wall, pre-agent, active-agent, post-agent, provider, and tool duration;
- cache state at turn 0 and steady-state cache share after turn 0;
- rate-limit, truncation, offload, and telemetry warnings.

Preserve failed attempts. Failed work consumes time and tokens.

### 4. Normalize without hiding the raw result

Report raw and controlled views side by side.

Use equal task weight: average attempts within each task, then sum or average task means. This estimates a random-k1 workload without giving long tasks extra weight merely because they use more turns.

Primary view:

- all attempts, including failures;
- task-balanced workload;
- actual harness cache policies.

Sensitivity views:

- solved-only;
- matched same-task trajectories with similar turn counts;
- equal cache TTL;
- leave-one-task-out;
- per-task and per-attempt variance;
- prior comparable runs.

Do not silently drop outliers. Explain how conclusions move with and without them.

### 5. Derive comparable context segments

Do not compare Iris's local base estimate with another harness's full first turn.

When repeated task-matched attempts exist:

1. Compare same-task first-turn full input across attempts and harnesses.
2. Isolate a stable provider-observed prefix only when deltas agree.
3. Verify that the task-specific suffix is identical or explain why it is not.
4. Split repeated input area into fixed prefix, task prompt, and dynamic post-turn-0 content.

Remember that input is an area over turns: a 10k prefix repeated for 20 turns contributes 200k input tokens.

Label estimates, provider observations, and algebraic derivations separately.

### 6. Calculate cost in distinct views

State prices and units. Never infer cache-write TTL from a generic write total when a class breakdown exists.

Report:

1. **Observed:** recorded warm/cold cache state as run.
2. **Cold product-policy:** normalize turn 0 while retaining each harness's native TTL and rates.
3. **Cold equal-TTL:** counterfactual that isolates prompt/trajectory behavior from TTL policy.
4. **Fixed/non-fixed:** remove the correctly matched fixed prefix from each harness.
5. **Spend per success:** total attempted spend divided by successful attempts.

If OAuth/subscription runs were not invoiced per token, call these API-equivalent cost estimates.

### 7. Analyze cache behavior correctly

Separate:

- turn-0 cache state;
- aggregate cache share;
- steady-state share after turn 0;
- weighted token share versus unweighted trial mean;
- content growth and breakpoint behavior;
- write TTL economics.

A low short-run aggregate cache percentage can be a cold-start/content-growth artifact. Prove a breakpoint defect from per-turn transitions, not from one aggregate ratio.

### 8. Decompose timing

Always report both product wall time and agent-loop time.

Split where evidence permits:

- pre-agent installation/startup;
- agent-active span;
- provider/model duration;
- tool duration;
- post-agent/verifier duration.

Call overlapping tool durations non-additive. Treat incomplete TTFT as unusable rather than representative.

### 9. Inspect failures and outliers in exact logs

Rank outliers by cost, output, duration, context growth, turn count, and within-task variance. Inspect each selected trial's surrounding session records and tool sequence.

Classify failures from evidence, not keywords:

- capability/task failure;
- destructive or unsafe action;
- agent timeout;
- tool timeout;
- verifier failure;
- infrastructure/auth/rate-limit failure;
- cancellation;
- mixed capability/resource-limit failure.

For output alarms, use non-overlapping severity bands by default:

- warning: provider output `>4,000` and `<=8,000` tokens;
- critical: provider output `>8,000` tokens.

Include trial, turn, output, duration, stop reason, and available visible-text/tool/reasoning split. Inspect adjacent records before naming a cause.

Iris provider turn IDs may be encoded as zero-padded hexadecimal strings. Map by chronological order or parse the ID correctly; do not assume decimal formatting.

Anthropic extended reasoning may appear as an `assistant_reasoning` record with empty content and an opaque `continuity` payload. In that case:

- do not claim to have read the reasoning text;
- do not decode or expose chain of thought;
- use the local token estimate, timing, adjacent tool calls, and results to classify the observable behavior;
- flag `reasoning: 0` as a telemetry gap if a reasoning record exists, using unknown rather than inventing an exact split.

Distinguish long visible answers, large tool arguments, large tool results, and opaque extended reasoning. “Runaway generation” is not a diagnosis until that split is checked.

### 10. Turn evidence into recommendations

Every recommendation must name:

- the measured problem;
- supporting trials/turns or aggregate evidence;
- the proposed intervention;
- the metric and safety/capability guardrail for an A/B test.

Prefer system-level causes over benchmark-specific answer hints. Do not optimize Iris to memorize a task. Avoid blind output or reasoning caps when difficult-task success may depend on them; test replan interventions or adaptive budgets first.

Prioritize:

- P0 accounting or experiment-validity defects;
- P0 next-run design fixes;
- P1 product efficiency changes;
- P1 telemetry gaps.

## Report structure

Use progressive disclosure:

1. Title and immutable run metadata.
2. Verdict: capability, cost, speed, and strongest caveat.
3. Corrections to prior headlines.
4. Method and source semantics.
5. Aggregate comparison.
6. Fixed/task/dynamic token decomposition.
7. Cost and cache decomposition.
8. Per-task behavior and failures.
9. Turn-count controls, variance, and sensitivity.
10. Tool/context behavior.
11. Latency and output/reasoning outliers.
12. Prior-run consistency.
13. Prioritized recommendations.
14. Bottom line.

Use exact denominators. Distinguish percentage points from percentages. State when the sample is too small for a capability claim.

## HTML presentation

Generate HTML from the Markdown source or the same structured data; never maintain contradictory prose by hand.

The HTML must be:

- self-contained: inline CSS, no remote fonts, scripts, or assets;
- responsive and readable on desktop and mobile;
- semantic: one `h1`, ordered headings, landmarks, skip link, table captions/labels, and valid internal anchors;
- navigable: sticky table of contents on wide screens, compact layout on narrow screens;
- scannable: 3-5 restrained KPI cards, strong hierarchy, generous spacing, and horizontally scrollable tables;
- accessible: sufficient contrast, visible focus styles, no color-only meaning;
- printable: dedicated print CSS that removes navigation and avoids clipped tables.

Use a restrained neutral canvas, one dark navigation color, one primary accent, and warning colors only for actual warnings. Prefer system sans-serif for body text and a system serif for major headings. Preserve the full evidence narrative below the dashboard.

## Verification gate

Before calling the report complete:

1. Re-run the analysis from the preserved job directories.
2. Run existing parser/analyzer tests.
3. Assert key report values against generated metrics.
4. Check token identities, matched task sets, cache classes, and success counts.
5. Confirm report copies are byte-identical where both work and archive copies exist.
6. Parse HTML and assert unique IDs, resolved internal links, expected section/table counts, and presence of key values.
7. Render the HTML in a headless browser at desktop size; also check the responsive layout when practical.
8. Search the report and archive log for stale superseded numbers.
9. Report any unverifiable field or incomplete instrumentation explicitly.

A polished report with unverified numbers is a failure. A correct analysis with an unreadable report is incomplete.
