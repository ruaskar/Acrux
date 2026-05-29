# /handoff — session catchup + memory graduation

> Generalized from the AOTC-Harness `/handoff` command (AOTC specifics scrubbed).
> A token-saver: compress a whole session into a small structured catchup +
> a paste-ready pickup block, so the next session reloads minimal context
> instead of replaying the full transcript.

When invoked, do the following (no confirmation gates):

1. **Write one catchup file per inferred project scope** to `_handoff/` with this schema:
   - **Narrative** — what this session set out to do and what actually happened.
   - **Progress** — concrete, verifiable state (commits, tests passing, files changed).
   - **Memories graduated** — durable learnings written to long-term memory this session.
   - **Obstacles** — what blocked or surprised you, with root cause.
   - **Reflection** — an honest self-assessment (what's solid, what's shaky, quantitative estimates where you have them).
   - **Next step** — a SINGLE, verifiable next action.
   - **Read list** — 3–7 files/artifacts the next session should read first, each with a one-line "why".
   - **Pickup prompt** — a paste-ready block to start the next session after compaction.

2. **Graduate durable learnings** into long-term memory (SCAN existing → classify supersedes/resonates/contradicts → WRITE + WIRE → INDEX one line).

3. **Emit the pickup block** so the next session can resume with minimal context.

The goal is that the next session reads the catchup + the 3–7 listed files and
is fully oriented — not the entire transcript.
