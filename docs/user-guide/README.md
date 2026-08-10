# Developer and Solution Designer Guide

How to design, build, test, evaluate, deploy and operate a business-specific
agentic solution **on this platform**.

This is not a tutorial about AI agents in general. Every contract, path, command
and configuration name here was read out of the repository, and anything the
platform does not yet do is labelled rather than described as if it did.

## Read in this order

| Document | For | Read when |
| --- | --- | --- |
| [Developer & Solution Guide](./developer-solution-guide.md) | Solution architects, tech leads | You have a business problem and need to turn it into an agentic design |
| [Internal Fitments reference](./internal-fitments-reference.md) | Everyone | You want a complete worked example, end to end |
| [Agent design guide](./agent-design-guide.md) | Developers | You are about to add or change an agent |
| [Tool development guide](./tool-development-guide.md) | Developers | You are giving an agent a new capability |
| [Evaluation guide](./agent-evaluation-guide.md) | Developers, QA | You need to know whether the thing works |
| [Development checklist](./agent-development-checklist.md) | Everyone | Before you call it done |

## The running example

Every document uses one business case throughout: **Internal Fitments**, the
internal staffing process described in
*Internal Fitments — Agentic Way* (Account Staffing, Globant). Six specialist
agents move a **Staff Request** (`SR-`) through evaluation, interview scheduling,
monitoring and a fitment decision, with **two human decision gates** that stay
human by design.

The example is there to teach the method. When you read "the Evaluation Agent
needs a structured output", the transferable lesson is about structured output —
candidate screening, invoice validation, document review and claims triage are
the same shape.

## The labels, and what they mean

The whole guide depends on these being used honestly.

| Label | Meaning |
| --- | --- |
| **Implemented** | It is in the repository, wired into the composition root, and covered by tests. A file path is given. |
| **Partially implemented** | The contract exists and is carried, but something downstream does not honour it yet. What is missing is stated. |
| **Not implemented — you build it** | The platform gives you the seam; the business capability is solution-team work. |
| **Not implemented — platform gap** | Neither exists. Building it means changing the platform, not your solution. |

If you find one of these labels is wrong, the code won. Fix the document.

## Related documentation

- [`.claude/architecture.md`](../../.claude/architecture.md) — the authoritative architecture document
- [`docs/adr/`](../adr/) — why each major decision was made
- [`docs/developer-setup.md`](../developer-setup.md) — getting a machine running
- [`docs/runbooks/`](../runbooks/) — deployment and operations
- [`docs/milestones/STATUS.md`](../milestones/STATUS.md) — what is verified, and what is known to be missing
