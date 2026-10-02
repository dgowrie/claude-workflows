# Repeatable Investigations

When an investigation produces numbers someone else will act on (a calibration, a benchmark, a "does this approach hold" check against live data), make it reproducible from the first query, not after the fact.

- **Script it.** A harness with fixed, past end times, never "now", so a rerun reads the same data.
- **Log every query:** the exact query, the datasource or endpoint, the evaluation time, and the value returned.
- **Replay before sharing.** Rerun the harness and confirm it reproduces the logged values. Then the claim rests on the data, not on one session's memory of it.
- **Keep the harness and log somewhere durable.** Not a scratchpad, `$TMPDIR`, or a browser tab: the people acting on the numbers need to reread and extend them.

**Why:** ad-hoc queries typed into a browser were lost when the tab closed and had to be rebuilt before the results could go to the owners deciding on them. A scripted rerun also showed that an earlier "refuted" result came from a formula slip, not from the data.

Related: [`epistemic-honesty`](epistemic-honesty.md) ("Testing a paraphrase": run the proposal exactly as stated, with the same math on identical raw data as a control).
