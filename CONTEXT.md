# Domain Context

## Detection run

A **Detection run** is one complete privacy audit for one APK. It can contain
multiple **Probe phases** and must keep enough durable state to resume after an
Appium session loss, App crash, pause, or device restart.

## Probe phase

A **Probe phase** is one controlled permission posture within a Detection run.
The normal order is `deny` followed by `allow`. The allow phase replays only
permission-relevant routes discovered by the deny phase; it is not a second
full traversal.

## Page observation

A **Page observation** is the raw Activity, accessibility tree, OCR text,
foreground package, and screenshot metadata captured at one instant. It is not
itself a unique business page.

## Page semantics

**Page semantics** is the single authoritative classification derived from a
Page observation. It identifies scope (audited App, Android system, or external
App), role (document, permission prompt, business hub, login, and so on), and
the actions that are safe on that page.

## Semantic navigation graph

The **Semantic navigation graph** stores business pages and verified
transitions. Its node identity includes App scope, Activity, Page semantics,
route context, and Probe phase. Scroll viewports and transient redraws are
states of a node rather than new business pages.

## Scenario execution

A **Scenario execution** is the stateful attempt to prove or disprove one legal
recognition-method item. It owns preconditions, steps, evidence requirements,
recovery, and terminal outcome. Merely clicking a related control is not a
completed Scenario execution.

## Permission probe

A **Permission probe** is a Scenario execution that binds a business action to
a system permission prompt and then verifies the deny or allow result against
the same business action.

## Document reading session

A **Document reading session** owns a document's semantic identity, source
route, content fingerprints, scroll progress, bottom confirmation, extracted
text, style evidence, and recovery checkpoint. A document title inherited from
an earlier page is never sufficient identity by itself.

## Action arbitration

**Action arbitration** selects one final action from deterministic, scenario,
navigation, and LLM proposals. Safety constraints are filters and cannot be
overridden by proposal priority.

## Deterministic decision module

A **Deterministic decision module** owns the priority, bounded retries, state
updates and audit event for one exploration domain such as consent, Permission
probe, login, privacy hub or SDK observation. It returns one immutable decision
directive; the traversal orchestrator may apply it but must not reimplement its
ordering.

## SDK observation checkpoint

An **SDK observation checkpoint** is the bounded post-entry dwell on a quiet
main-content surface used to observe collection that may begin after consent.
It can navigate to that surface, dwell once, or record that no such surface was
reachable; it may never hold the traversal in an unbounded wait/back loop.

## Action effect

An **Action effect** is the verified semantic result of an Appium command:
a changed Page observation, a permission prompt, or a bounded no-effect
outcome. Command success alone is not navigation success.

## Completion gate

The **Completion gate** is the only authority allowed to call rule coverage
complete. It separately records whether the safe navigation frontier is
exhausted. A run may truthfully exhaust reachable UI while retaining explicit
coverage gaps for unavailable login, server, or scenario evidence. It also
reconciles active Document reading sessions, Permission probes and pending
Action effects; a local `back` with no progress is never completion by itself.

## Surface budget

A **Surface budget** is keyed by stable Page semantics, never an App or page
name. Commercial, tutorial, empty-state and other low-audit-value pages receive
one observation and one bounded exit, while privacy, permission, redress and
account controls remain exempt from pruning.

## Automatic capability status

An **Automatic capability status** records whether a check was executed,
produced violation evidence, produced no violation evidence, or was not
executed because required DOM/CSS, credentials, network, or server evidence
was unavailable.

## Evidence chain

An **Evidence chain** is the ordered, rule-scoped set of observations and
actions required for adjudication. Evidence collected by UI, document, Frida,
network, and screenshot adapters is reconciled rather than silently discarded
when one source is incomplete.
