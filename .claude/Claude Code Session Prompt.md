# Claude Code Session Prompt
# Enterprise Multi-Agent AI Platform — Developer & Solution Designer Guide

You are the **Lead AI Solution Architect, Agentic AI Architect, Developer Experience Architect, and Technical Documentation Lead** for this repository.

The platform has now been implemented and committed.

Your task is to create the **official Developer & Solution Designer User Manual** for this platform.

The manual must teach developers, AI engineers, solution architects, and technical leads how to use this platform to design, build, test, evaluate, deploy, and operate new business-specific agentic AI solutions.

This must be a **platform-specific development guide**, not a generic tutorial about AI agents.

---

# 1. CRITICAL SOURCE-OF-TRUTH RULE

Before writing any documentation, inspect the actual repository implementation.

Read and understand:

- `CLAUDE.md`
- `project-spec.md`
- `architecture.md`
- `engineering-handbook.md`
- `docs/adr/`
- `docs/architecture/`
- `docs/milestones/`
- backend source
- frontend source
- API contracts
- configuration
- agent runtime
- workflow runtime
- LLM Gateway / provider implementation
- model configuration
- tool framework
- memory
- observability
- evaluation
- tests
- Docker
- Azure infrastructure
- CI/CD
- README files

The **implemented code is the ultimate source of truth**.

Do not assume that existing design documents exactly match the implementation.

If documentation and implementation differ:

1. Identify the difference.
2. Determine actual implemented behavior from the code.
3. Document the actual behavior.
4. Identify the documentation gap.
5. Do not silently invent functionality.
6. Do not modify application code during this documentation task unless explicitly approved.

Clearly distinguish:

- **Implemented**
- **Planned**
- **Recommended/Future**

Never describe planned or recommended functionality as already implemented.

---

# 2. ATTACHED REFERENCE SOLUTION — MANDATORY

Use the attached document:

**Internal Fitments - Agentic Way.pdf**

as the **primary business example** throughout this guide.

Do NOT replace it with the generic Incident Resolution example.

The Internal Fitments solution is the canonical example used to explain how a real business process can be transformed into an agentic solution on this platform.

The document describes an internal staffing / fitment process in which candidates are evaluated against positions, internal interviews are scheduled and monitored, decisions are made by people at defined gates, and downstream reporting, notifications, and staffing actions are coordinated by specialized agents.

Use the terminology and conceptual framing from the document.

Do not silently change the business meaning.

---

# 3. REFERENCE SOLUTION — INTERNAL FITMENTS

Build the developer guide around this example.

The reference solution contains six specialist agents:

1. Orchestrator Agent
2. Evaluation Agent
3. Scheduling Agent
4. Monitoring Agent
5. Reporting Agent
6. Notification Agent

The reference document intentionally gives each agent a narrow responsibility rather than creating one large autonomous agent.

The guide must explain this as a core platform design principle:

> Prefer specialized, composable agents with clear responsibilities over one large general-purpose agent.

---

# 4. BUSINESS PROCESS EXAMPLE

Explain the Internal Fitments process before explaining the technology.

The process should be presented approximately as:

```text
Position / JD
     |
     v
Candidate Evaluation
     |
     v
AI-ranked Shortlist
     |
     v
Human Decision Gate
     |
     v
Internal Interview
     |
     v
Interview Monitoring
     |
     v
Interview Transcript / Feedback
     |
     v
Human Decision Gate
     |
     +---- Internal Fit
     |
     +---- Internal Fit Rejected
     |
     v
Reporting / Staffing / Notification
```

Use the actual source document to refine this flow.

The document describes candidates moving through defined stages and identifies human decision gates around progression and final Internal Fit / Reject decisions.

---

# 5. WHAT THE AGENTS DO

Create a dedicated section explaining each reference agent.

## 5.1 Orchestrator Agent

Explain:

- Overall coordination
- Current position/status
- Approval gates
- Agent handoffs
- User-facing status queries
- Coordination rather than performing every business task

The reference design explicitly positions the Orchestrator around the position's current state and approval gate.

Explain why the Orchestrator should NOT perform all specialist tasks itself.

---

## 5.2 Evaluation Agent

Explain:

- Reading JD and candidate CVs
- Candidate ranking
- Matching candidates against requirements
- Producing reasoning
- Producing structured results
- Reusing evaluation results rather than unnecessarily repeating work

The reference solution describes the Evaluation Agent as reading the JD and candidate CVs and producing ranked candidates with strengths, gaps, and rationale.

Use this to demonstrate:

- Structured output
- Document processing
- Candidate scoring
- Explainability
- Idempotency
- Reusable agent results

---

## 5.3 Scheduling Agent

Explain:

- Interviewer matching
- Availability
- Interview booking
- Invitation handling
- Scheduling constraints
- Rescheduling

The reference design describes the Scheduling Agent as matching approved candidates to interviewers and booking the interview while avoiding conflicts.

Use this agent to demonstrate:

- Tool usage
- External system integration
- Constraints
- Side effects
- Idempotency
- Error handling

---

## 5.4 Monitoring Agent

Explain:

- Interview monitoring
- SLA tracking
- Response tracking
- Transcript handling
- Feedback monitoring
- Escalation

The reference solution describes continuous monitoring of interview state and SLA, routing transcript summaries, and escalating when required.

Use this agent to demonstrate:

- Event-driven thinking
- Scheduled/background execution
- State transitions
- SLA monitoring
- Automated follow-up

---

## 5.5 Reporting Agent

Explain:

- Fulfilment summaries
- Position status
- Candidate status
- Account-level reporting
- User questions about current state

The reference design positions Reporting as the agent that provides fulfillment reports and role-based summaries.

Use this agent to demonstrate:

- Read-only agents
- Aggregation
- Natural-language queries over structured state
- Business dashboards

---

## 5.6 Notification Agent

Explain:

- Slack/email notifications
- Event-driven notifications
- Avoiding duplicate notifications
- Notification audit history

The reference design identifies Notification as the single notification gateway so that other agents do not independently send duplicate messages.

Use this as a key architecture principle:

> Centralize cross-cutting side effects when multiple agents need the same capability.

---

# 6. AGENT-TO-AGENT COMMUNICATION

The reference solution introduces an important concept:

## Agent Contract

Each agent publishes a machine-readable description of:

- Name
- Capabilities
- Inputs
- Outputs
- Skills
- Expected invocation
- Completion state

The reference document describes this as a machine-readable agent contract used to determine which agent should handle the next step and prevent duplicate work.

Make this a major section of the developer guide.

Explain:

### Agent Contract

```text
Agent
 |
 +-- Identity
 +-- Responsibility
 +-- Inputs
 +-- Outputs
 +-- Capabilities
 +-- Preconditions
 +-- Completion criteria
 +-- Error states
```

Explain how this maps to the actual implementation.

---

# 7. STATE-DRIVEN AGENTIC DESIGN

Use the Internal Fitments example to explain that agents should operate around **business state**, not merely conversations.

The reference document describes a position moving through defined stages and each agent acting according to the current state.

Teach the following principle:

```text
Business State
      |
      v
Determine Required Action
      |
      v
Select Agent
      |
      v
Execute
      |
      v
Update State
      |
      v
Trigger Next Step
```

Explain:

- State ownership
- State transitions
- Idempotency
- Event handling
- Recovery
- Auditability

---

# 8. HUMAN-IN-THE-LOOP DESIGN

This must be one of the most important sections.

The reference solution explicitly preserves human decision gates rather than allowing agents to make every business decision.

Explain:

## Automated

Examples:

- Candidate ranking
- Interviewer matching
- Scheduling
- SLA monitoring
- Notifications
- Status aggregation
- Reporting

## Human Decision

Examples:

- Approve/reject candidate progression
- Internal Fit decision
- Interview outcome
- High-impact business decisions

Use a table:

| Activity | Agent | Human | Reason |
|---|---|---|---|
| Candidate ranking | Evaluation | | Automated analysis |
| Shortlist approval | | PM/Service Line Leader | Business decision |
| Interview scheduling | Scheduling | | Coordination |
| Interview assessment | | Interviewer | Human judgment |
| Internal Fit decision | | PM/Service Line Leader | Business decision |
| Notification | Notification | | Automated side effect |

Update this based on the actual reference document.

---

# 9. BEFORE vs AFTER

Use the reference document's "Before / Now" framing.

The document contrasts manual activities such as manually screening CVs, checking interviewers, chasing responses, updating trackers, and asking people for status with automated agentic capabilities.

Create a section:

# From Manual Process to Agentic Solution

Show:

```text
BEFORE

Spreadsheet
+
Email
+
Slack
+
Manual follow-up
+
Manual status tracking
+
Manual reporting

        ↓

AGENTIC PLATFORM

Specialized Agents
+
Shared Business State
+
Tools
+
Workflow
+
Human Decision Gates
+
Observability
+
Auditability
```

Explain that the goal is not simply "replace humans."

The goal is:

> Automate coordination and repeatable work while preserving human ownership of business decisions.

---

# 10. ROLE-BASED EXPERIENCE

The reference solution demonstrates different experiences for:

- Project Manager
- Service Line Leader
- Staffing Lead

The document explains how each role interacts differently with the same underlying agentic system.

Use this to explain:

- Role-based access
- Role-based views
- Role-specific agents/capabilities
- Same business state, different user experience
- Authorization

Create a diagram:

```text
                    Shared Business State
                           |
             +-------------+-------------+
             |             |             |
             v             v             v
        Project Manager  Service Line   Staffing Lead
                           Leader
             |             |             |
             v             v             v
       Role-specific   Role-specific   Role-specific
          views            views           actions
```

---

# 11. REFERENCE AGENT ARCHITECTURE

Create a complete architecture diagram based on the attached document and actual platform implementation.

Conceptually:

```text
                         User
                          |
                          v
                     Chat Interface
                          |
                          v
                     API / Gateway
                          |
                          v
                    Orchestrator
                          |
          +---------------+----------------+
          |               |                |
          v               v                v
     Evaluation      Scheduling       Reporting
          |               |
          v               v
      Candidate        Interview
       Results          Booking
                          |
                          v
                     Monitoring
                          |
                          v
                   Transcript /
                    Feedback
                          |
                          v
                  Human Decision
                          |
             +------------+------------+
             |                         |
             v                         v
      Internal Fit              Internal Fit
                                  Rejected
             |                         |
             +------------+------------+
                          |
                          v
                    Notification
```

Adapt this diagram to the actual repository architecture.

---

# 12. MAP THE BUSINESS SOLUTION TO THE PLATFORM

This is one of the most important parts of the guide.

Create a table:

| Internal Fitments Concept | Platform Capability | Repository Implementation |
|---|---|---|
| Evaluation Agent | Agent Runtime | Actual path |
| Scheduling Agent | Agent + Tools | Actual path |
| Monitoring Agent | Workflow/Background execution | Actual path |
| Reporting Agent | Agent + Query tools | Actual path |
| Notification Agent | Tool/Notification service | Actual path |
| Orchestrator | Agent/Workflow runtime | Actual path |
| Agent Contract | Agent metadata/interface | Actual path |
| Candidate state | State model | Actual path |
| Human approval | Approval mechanism | Actual path |
| Model selection | Model Registry | Actual path |
| LLM invocation | LLM Gateway | Actual path |
| Memory | Session/Memory service | Actual path |
| Observability | Telemetry | Actual path |
| Evaluation | Evaluation framework | Actual path |

DO NOT invent repository paths.

Inspect the implementation and populate the table with real paths.

If something does not yet exist in the platform, mark it:

**Not currently implemented — recommended/future capability.**

---

# 13. HOW TO CREATE A NEW BUSINESS SOLUTION

After teaching the Internal Fitments example, abstract the lessons into a reusable methodology.

Use:

```text
1. Understand the business process
2. Identify business states
3. Identify decisions
4. Separate human decisions from automatable work
5. Identify agent boundaries
6. Define agent contracts
7. Define shared state
8. Define tools
9. Define permissions
10. Select models
11. Define memory
12. Define workflow
13. Define guardrails
14. Define observability
15. Define evaluation
16. Implement
17. Test
18. Deploy
19. Monitor
20. Improve
```

For every step provide:

- Questions to ask
- Design decisions
- Platform capability
- Internal Fitments example
- Common mistake

---

# 14. WHEN TO CREATE A NEW AGENT

Teach developers not to create agents unnecessarily.

Use these principles:

Create a separate agent when:

- Responsibility is clearly different.
- Required tools are different.
- Model requirements differ.
- Security/permissions differ.
- Lifecycle differs.
- Evaluation criteria differ.
- It can operate independently.
- The separation improves maintainability.

Do NOT create a separate agent merely because a task has a different prompt.

Use the Internal Fitments six-agent architecture as the primary example.

---

# 15. MODEL SELECTION PER AGENT

Explain that different agents may use different models.

For the Internal Fitments example, illustrate conceptually:

```text
Evaluation Agent
      |
      v
High-quality document reasoning model

Scheduling Agent
      |
      v
Tool-capable low-latency model

Monitoring Agent
      |
      v
Efficient low-cost model

Reporting Agent
      |
      v
Fast model

Orchestrator
      |
      v
Model selected according to orchestration complexity
```

Do NOT hardcode models unless the actual repository supports them.

Explain how developers configure model selection using the actual platform mechanism.

Also explain:

- Capability
- Cost
- Latency
- Context length
- Tool calling
- Structured output
- Reasoning requirements

---

# 16. OPENAI-COMPATIBLE MODEL ARCHITECTURE

The platform has been intentionally designed so that future OpenAI-compatible endpoints can be used.

Explain this architecture:

```text
Business Agent
      |
      v
LLM Gateway
      |
      v
Provider-Neutral Contract
      |
      +---- Azure AI Foundry
      |
      +---- Future OpenAI-Compatible Endpoint
```

Explain that business agents should not directly depend on:

- Azure AI Foundry SDK
- OpenAI SDK
- Provider-specific request models
- Provider-specific response models

Show developers how this architectural boundary allows future model/provider changes without rewriting agents.

Use ADR-006 as the architectural reference.

---

# 17. TOOL DESIGN

Use the Internal Fitments example to explain tool design.

Potential conceptual tools include:

- Candidate document retrieval
- Candidate evaluation data access
- Interviewer availability lookup
- Interview scheduling
- Interview status lookup
- Transcript retrieval
- Staffing portal update
- Notification sending

Do not claim these tools are implemented unless they actually exist.

For each tool explain:

- Purpose
- Input
- Output
- Read vs write
- Authorization
- Idempotency
- Error handling
- Timeout
- Retry
- Audit

---

# 18. SIDE EFFECTS

The reference solution is particularly useful for teaching side-effect management.

Examples:

- Sending invitations
- Sending notifications
- Updating staffing records
- Reserving/releasing candidates
- Scheduling interviews

Explain that side-effecting operations require:

- Explicit authorization
- Idempotency
- Auditability
- Error handling
- Retry strategy
- Human approval where appropriate

---

# 19. OBSERVABILITY

Explain what developers should observe for every agent:

- Agent invocation
- Model invocation
- Token usage
- Latency
- Tool invocation
- Tool failure
- Workflow state
- Human approval
- Agent handoff
- Final outcome
- Cost

Use the Internal Fitments example to show why "status visibility" is more important than simply generating reports.

The reference document explicitly emphasizes having current, visible status rather than manually compiling status reports.

---

# 20. EVALUATION

Use the Evaluation Agent as the main example for evaluation-driven development.

Explain:

- Golden datasets
- Expected outputs
- Candidate ranking quality
- Tool accuracy
- Workflow completion
- Human override rate
- False positives
- False negatives
- Latency
- Cost

Create an example evaluation matrix.

Clearly distinguish:

- Platform evaluation capabilities that actually exist
- Recommended evaluation practices not yet implemented

---

# 21. COST MANAGEMENT

Explain:

- Model selection
- Token usage
- Agent frequency
- Background monitoring
- Tool calls
- Duplicate execution
- Caching
- Reusing results

Use the Internal Fitments example to explain why an agent should not repeatedly perform the same evaluation or notification.

---

# 22. SECURITY & GOVERNANCE

Use Internal Fitments as an enterprise example.

Cover:

- Candidate data
- CVs
- Interview transcripts
- Staffing information
- Role-based access
- Sensitive information
- Agent permissions
- Tool permissions
- Human approvals
- Audit logs
- Data retention
- Prompt injection
- Unauthorized actions

Do not invent compliance claims.

---

# 23. TESTING A NEW AGENTIC SOLUTION

Create a complete testing methodology:

### Unit Testing

### Tool Testing

### Agent Testing

### Workflow Testing

### Integration Testing

### End-to-End Testing

### Evaluation Testing

### Security Testing

### Failure Testing

Use Internal Fitments scenarios such as:

- Candidate cannot be evaluated.
- Interviewer unavailable.
- Interview invitation not accepted.
- SLA breached.
- Transcript unavailable.
- Human rejects candidate.
- Duplicate notification attempt.
- Staffing update fails.
- Agent retries an already completed action.

---

# 24. AGENT DESIGN TEMPLATE

Create a reusable template based on the actual platform.

Conceptually include:

```yaml
agent:
  name:
  purpose:
  responsibility:
  inputs:
  outputs:
  model:
  tools:
  memory:
  permissions:
  triggers:
  handoffs:
  guardrails:
  human_approval:
  evaluation:
  observability:
```

IMPORTANT:

If the actual platform has a different configuration format, use the actual implementation format.

Do not introduce YAML merely for documentation convenience.

---

# 25. AGENT DEVELOPMENT CHECKLIST

Create a practical checklist:

```text
[ ] Business objective defined
[ ] Business state identified
[ ] Agent responsibility clearly bounded
[ ] Human vs automated decisions defined
[ ] Agent contract defined
[ ] Inputs defined
[ ] Outputs defined
[ ] Model selected
[ ] Tools identified
[ ] Tool permissions defined
[ ] Memory requirements defined
[ ] Handoffs defined
[ ] Guardrails defined
[ ] Human approval assessed
[ ] Evaluation criteria defined
[ ] Cost considered
[ ] Observability verified
[ ] Security reviewed
[ ] Tests created
[ ] Documentation completed
```

---

# 26. AGENTIC DESIGN PATTERNS

Use Internal Fitments to explain:

1. Orchestrator
2. Specialist Agent
3. Sequential Agent Chain
4. Human Decision Gate
5. Tool-Using Agent
6. Background Monitoring Agent
7. Notification Gateway
8. Reporting Agent
9. Shared State
10. Agent Contract
11. Idempotent Agent Action

For each pattern explain:

- What it is
- When to use it
- When not to use it
- Internal Fitments example
- Platform implementation

---

# 27. ANTI-PATTERNS

Create a strong anti-pattern section.

Include:

- One giant agent
- Agent duplication
- Agents with overlapping responsibilities
- Every agent having every tool
- Agents making human business decisions
- Uncontrolled side effects
- No state model
- No agent contract
- No idempotency
- No audit
- No evaluation
- Hardcoded model
- Provider-specific business logic
- Excessive agent-to-agent communication
- Infinite agent loops
- Excessive background polling
- Unbounded cost
- Treating reports as the primary source of truth instead of live business state

Use examples from Internal Fitments where applicable.

---

# 28. DEVELOPER WORKFLOW

Create a complete workflow for building a new business solution:

```text
Business Workshop
       |
       v
Business Process Model
       |
       v
State Model
       |
       v
Agent Boundary Design
       |
       v
Agent Contracts
       |
       v
Tools
       |
       v
Models
       |
       v
Workflow
       |
       v
Human Decision Gates
       |
       v
Security
       |
       v
Evaluation
       |
       v
Implementation
       |
       v
Testing
       |
       v
Deployment
       |
       v
Observability
       |
       v
Continuous Improvement
```

---

# 29. ROLE OF PLATFORM VS SOLUTION TEAM

Clearly explain:

## Platform Team Owns

- Core runtime
- LLM Gateway
- Provider abstraction
- Model registry
- Tool framework
- Workflow framework
- Memory framework
- Observability
- Security infrastructure
- Evaluation infrastructure
- Deployment platform

## Solution Team Owns

- Business agents
- Business prompts
- Business workflows
- Business tools
- Business data integration
- Business policies
- Business evaluation datasets
- Business-specific configuration

This distinction is critical for platform scalability.

---

# 30. DOCUMENTATION DELIVERABLES

Create:

```text
docs/user-guide/
    developer-solution-guide.md
    internal-fitments-reference.md
    agent-design-guide.md
    tool-development-guide.md
    agent-evaluation-guide.md
    agent-development-checklist.md
```

If the repository already has a suitable documentation structure, reuse it instead of creating a competing structure.

---

# 31. DIAGRAMS

Use Mermaid diagrams wherever useful.

At minimum include:

1. Platform Architecture
2. LLM Provider Architecture
3. Agent Lifecycle
4. Internal Fitments Business Process
5. Internal Fitments Multi-Agent Architecture
6. Agent-to-Agent Communication
7. Human Decision Gates
8. Tool Execution
9. State Transition
10. Evaluation Lifecycle
11. Developer Lifecycle

All diagrams must reflect the actual platform implementation.

---

# 32. REFERENCE SOLUTION TRACEABILITY

For every major platform concept, explicitly connect it to Internal Fitments.

Use this structure:

```text
Platform Concept
      |
      v
Internal Fitments Example
      |
      v
Implementation Pattern
      |
      v
How to Reuse for Another Business
```

For example:

```text
Specialized Agent
      |
      v
Evaluation Agent
      |
      v
Agent + Model + Tools + Structured Output
      |
      v
Reuse for:
Candidate screening
Invoice validation
Document review
Claims processing
```

This makes the manual reusable rather than merely describing one solution.

---

# 33. TROUBLESHOOTING

Include:

- Agent not invoked
- Wrong agent invoked
- Wrong model selected
- Tool failure
- Duplicate action
- Workflow stuck
- Human approval not triggered
- Notification duplicated
- State not updated
- Memory unavailable
- LLM provider failure
- High latency
- High token usage
- Unexpected cost
- Missing telemetry
- Authorization failure

Base troubleshooting on actual repository behavior.

---

# 34. FAQ

Include:

- When should I create a new agent?
- When should I reuse an existing agent?
- How do I decide agent boundaries?
- When should I use a workflow instead?
- How do agents communicate?
- How is business state maintained?
- How do I select a model?
- Can different agents use different models?
- How do I add a tool?
- How do I implement a side-effecting tool?
- How do I add human approval?
- How do I add an OpenAI-compatible LLM endpoint?
- How do I test an agent?
- How do I evaluate an agent?
- How do I measure cost?
- How do I deploy a business solution?

---

# 35. IMPORTANT DOCUMENTATION QUALITY RULES

The guide must be:

- Practical
- Developer-oriented
- Architecture-aware
- Implementation-specific
- Enterprise-oriented
- Example-driven

Avoid generic AI theory unless necessary to explain a platform design decision.

Use actual repository paths.

Use actual commands.

Use actual APIs.

Use actual configuration names.

Do not invent implementation details.

---

# 36. FINAL REVIEW

Before completing the work:

1. Compare every technical statement with the repository.
2. Verify every referenced file exists.
3. Verify every command.
4. Verify configuration names.
5. Verify API paths.
6. Verify architecture diagrams.
7. Verify agent terminology.
8. Verify Internal Fitments terminology against the attached reference document.
9. Clearly distinguish implemented vs planned vs recommended functionality.
10. Check that the guide can actually be followed by a developer who has never worked on this platform.

---

# 37. FINAL DELIVERABLE REPORT

At the end provide:

## Documentation Created

List every file.

## Platform Capabilities Documented

Summarize what was discovered.

## Internal Fitments Mapping

Show how the reference solution maps to the platform.

## Gaps

Identify:

- Platform implementation gaps
- Existing documentation gaps
- Recommended future improvements

Do not fix these automatically.

## Quality Validation

Report what was verified.

## Suggested Git Commit

Provide:

```text
docs: add developer and solution designer guide
```

Do not commit changes unless explicitly instructed.

---

# FINAL INSTRUCTION

The objective is to make this documentation good enough that a new Solution Architect can receive a business problem and answer:

> "How should I design this as an agentic solution using our platform?"

and a developer can then answer:

> "Exactly how do I implement it using the platform's existing architecture, contracts, agents, tools, models, memory, workflows, evaluation, and observability?"

The **Internal Fitments – Agentic Way** solution must be the primary running example used to teach that journey.

Do not turn the guide into documentation of the Internal Fitments business process alone.

Use Internal Fitments to teach the **general platform design methodology**.
