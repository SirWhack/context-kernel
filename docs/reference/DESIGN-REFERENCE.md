# PoSD Modules & Interfaces — Working Reference

A working reference distilled from John Ousterhout's *A Philosophy of Software Design* (1st ed., 2018), focused on the chapters covering modules and interfaces (Ch. 4 "Modules Should Be Deep", Ch. 5 "Information Hiding (and Leakage)", Ch. 6 "General-Purpose Modules are Deeper", Ch. 7 "Different Layer, Different Abstraction", Ch. 8 "Pull Complexity Downwards", Ch. 9 "Better Together Or Better Apart?", Ch. 10 "Define Errors Out Of Existence", Ch. 13 "Comments Should Describe Things that Aren't Obvious from the Code"). Source confirmation: book TOC and Ousterhout's Stanford CS 190 lecture notes ([CS190 Modular Design](https://web.stanford.edu/~ouster/cgi-bin/cs190-winter18/lecture.php?topic=modularDesign), [CS190 Book Review](https://web.stanford.edu/~ouster/cgi-bin/cs190-winter21/lecture.php?topic=bookReview)).

For each concept: Ousterhout's framing, the diagnostic question, and the most common mistake.

---

## 1. Modules and interfaces (Ch. 4.1–4.3)

A **module** is a unit of code "relatively independent" of others. Its **interface** has two parts:

- **Formal interface** — method signatures, public variables, types.
- **Informal interface** — overall behavior, side effects, ordering constraints, thread-safety, error semantics. *"Informal aspects can only be described with comments."* (CS190)

**Abstraction** = "a simplified view of something that omits unimportant details." A module's interface *is* its abstraction. Goal: *"define simple abstractions that provide rich functionality."* (CS190)

- **Diagnostic:** What does a caller need to know to use this module correctly? Is all of that in the formal signature, or is some of it tribal knowledge / required call ordering / "you have to construct X before Y"?
- **Most common mistake:** treating the formal signature as the whole interface. Side effects, mutation, required ordering, and exception types are part of the contract whether you document them or not.

## 2. Deep vs. shallow modules (Ch. 4.4–4.6)

The depth metaphor: a module is a rectangle. Width = interface surface area (how much a user must learn). Area = total functionality. **Depth = area / width.** Deep is good.

- **Deep:** small interface, lots of functionality, lots of information hidden (Unix file I/O — five calls hide an entire filesystem).
- **Shallow:** "Complex interface and/or not much functionality. Invoking a method isn't much easier than just typing in the code of the method." (CS190)

Recognising shallow modules:
- Wrapper classes that mostly forward to a delegate.
- Methods whose signature is as wide as the body (`def set_x(self, x): self.x = x`).
- Classes whose public surface tells you exactly what fields are inside.

**Classitis** is Ousterhout's name for the cult of small classes — the belief that "classes should be small" pushed past the point where each new class adds more interface than it hides.

- **Diagnostic:** "Is invoking this method materially easier than inlining its body?" If no, the module isn't paying for its interface.
- **Most common mistake:** splitting a class because it "feels too big," producing two shallow classes whose combined interface is wider than the original.

## 3. Information hiding vs. information leakage (Ch. 5.1–5.3)

**Information hiding:** each module encapsulates a design decision; only that module knows it; the implementation can change without rippling.

**Information leakage:** *"a design decision is reflected in multiple modules"* — same fact has to be known in two places, so changing it requires editing both. Anything in the formal interface is leaked by definition; the goal of design is to minimise what has to leak.

**Temporal decomposition** is Ousterhout's flagship leakage anti-pattern: structuring code so each module corresponds to a phase of execution (read → parse → process → write). Adjacent phases end up sharing format knowledge, so the same design decision (the file format, the protocol layout) is now smeared across multiple modules. *"One of the most common causes of information leakage."* (CS190)

Other leakage forms:
- **Back-doors / configuration knobs** that expose internal state.
- **Shared types** that force callers to import the module's internal vocabulary.
- **Required call ordering** (`open()` before `read()` before `close()` with no enforcement).

- **Diagnostic:** "If this design decision changed, how many modules would I have to edit?" More than one = leak.
- **Most common mistake:** organising by *when* things happen rather than by *what knowledge* is needed. Pipelines and ETL stages are notorious.

**Coordinator-class implication:** if your coordinator knows the shape of every collaborator's internal state to wire them together (sequence numbers, internal IDs, retry counters), that knowledge has leaked upward. Push it back down.

## 4. General-purpose vs. special-purpose modules (Ch. 6)

Ousterhout's rule: **"somewhat general-purpose."** Not maximally generic (you can't predict future use) and not narrowly specialised to today's one caller (the API will encode caller-specific details and break under the second caller).

The questions Ousterhout names (Ch. 6.5, also CS190):
- *"What is the simplest interface that will cover all my current needs?"* — fewer methods is better, provided each method gets deeper.
- *"In how many situations will this method be used?"* — methods used in only one place are suspect.
- *"Is this API easy to use for my current needs?"* — generality must not destroy ergonomics.
- *"Does the API have to specialise for the current use, or can it stay general?"*

Generality tends to *improve* information hiding: a general API forces you to stop describing the caller's workflow in the signature.

- **Diagnostic:** does the method name embed a caller's use case (`get_tickets_for_step_panel_render()`)? Specialise the *caller*, not the API.
- **Most common mistake:** writing the API to fit today's single caller (over-specialising), then later bolting on flags for the second caller. Result: a shallow, special-purpose interface with configuration creep.

## 5. Different layer, different abstraction (Ch. 7)

Adjacent layers should provide *different* abstractions. If layer N looks like layer N±1, the layer is not earning its keep.

Red flags (each is a chapter section):
- **Pass-through methods** (7.1): "a pass-through method is one that does nothing except pass its arguments to another method, usually with the same API." Indicates the boundary between the two classes is in the wrong place.
- **Pass-through variables** (7.5): a piece of data threaded through several layers that don't use it, just so a deep layer can reach it. The middle layers now know about something irrelevant to their abstraction.
- **Decorator overuse** (7.3): each decorator that just adds a little to the wrapped object usually makes things shallower; consider folding into the underlying class or making a peer class.
- **Interface duplication** without added abstraction (7.2) — sometimes legitimate (e.g. `Dispatcher` exposes the same `dispatch()` shape as its delegates), but only when the wrapper is itself adding a real abstraction (uniform routing).

- **Diagnostic:** "What new vocabulary does this layer introduce?" If the answer is "none, it just calls down," the layer is a candidate for collapse.
- **Most common mistake:** introducing a layer "for separation of concerns" that simply forwards. The concerns weren't actually separated; the call stack just got taller.

**Coordinator-class implication:** a coordinator that exposes `coordinator.context.get_x()` and `coordinator.tool_runner.run()` is exporting its collaborators' interfaces — sibling layers leaking through. Either re-expose with a coordinator-level abstraction or stop having a coordinator wrapper.

## 6. Pull complexity downward (Ch. 8)

*"It's more important for a module to have a simple interface than a simple implementation."* (Ch. 4 / CS190) The author of the module should absorb pain so that N callers don't each pay it.

Ousterhout's archetype example (Ch. 8.2): **configuration parameters as a code smell.** A configuration parameter is the module saying "I don't know the right value, you figure it out." But the user has *less* information than the module does. Prefer to compute the value internally (e.g. measure RTT to derive a retry interval rather than expose `retry_interval_ms`).

Legitimate configuration: when the *policy* genuinely belongs to the caller (timeouts the caller's SLA dictates, feature flags). Illegitimate: tuning knobs that exist because the author didn't want to decide.

- **Diagnostic:** for every config parameter, ask: "Does the *caller* actually have information that lets them set this better than the module could?" If no, the module owes it an internal default — or better, an internal computation.
- **Most common mistake:** exposing options to "give callers flexibility." Almost always this is the module pushing its uncertainty upward.

**Coordinator-class implication:** every constructor parameter on a deep collaborator that the coordinator threads through from its own constructor is a complexity-upward arrow. Either the collaborator should compute it, or the coordinator should encapsulate it.

## 7. Better together or better apart (Ch. 9)

Combine when:
1. **Information is shared** — both pieces depend on the same design decision (file format, schema, protocol). Splitting causes leakage.
2. **The combined interface is simpler** — e.g. removing a method that only existed to bridge the two halves.
3. **There is duplication** — the same logic appears in both, and a unified module would absorb it.
4. **They are always used together** — one is meaningless without the other.

Split when:
1. **General-purpose mixed with special-purpose** — extract the general core (the most important rule; this is the "deep general module + thin specialisation" pattern).
2. **Different abstractions** — they happen to share a class but conceptually live at different levels.
3. **Different change rates** for unrelated reasons.

- **Diagnostic:** "If I changed X here, would I also have to change Y there?" Yes → merge. "Is one half meaningful without the other?" No → merge. "Do these two halves share *no* design decision?" → split.
- **Most common mistake:** splitting because a file got long. Length is the weakest signal; shared design decisions trump it.

## 8. Define errors out of existence (Ch. 10)

*"Reducing the number of exceptions that have to be handled is one of the best techniques for reducing complexity."* The fewer error paths in the interface, the deeper the module.

Techniques:
- **Redefine semantics** so the error can't happen. `unset(key)` succeeds whether or not the key exists — postcondition is "key is not in the map," which is true either way. `substring(start, end)` clips out-of-bounds rather than throwing.
- **Mask at a low level** where the module has the information to handle it (TCP retransmits internally rather than exposing packet loss).
- **Aggregate** error handling — one place that knows what to do, not every caller.

What it isn't: ignoring errors, catching-and-swallowing, returning sentinel values that callers must check. The point is to make the abstraction *truthful* about a smaller set of failure modes, not to hide real ones.

- **Diagnostic:** for each `raise` in the module, ask "could the postcondition be redefined so this isn't an error?" or "could this be handled here rather than reported?"
- **Most common mistake:** treating exceptions as defensive engineering — "more `raise` = more rigorous." Each exception added to the interface widens it; programmers think they're tightening it.

## 9. Comments as part of the interface (Ch. 13)

Because the formal interface can't express the informal interface, comments are *part of the contract*. Ousterhout's specific guidance:

- Interface comments document **what the caller needs to know that isn't in the signature** — invariants, side effects, units, error modes, threading.
- *"Implementation documentation contaminates [the] interface when interface documentation describes implementation details that aren't needed in order to use the thing being documented."* ([Sébastien notes](https://notes.portebois.net/2021/03/04/13.html))
- The naming red flag: *"If it's hard to find a simple name for a variable or method that creates a clear image of the underlying object, that's a hint that the underlying object may not have a clean design."* If the comment fights you, the abstraction is wrong.
- **Different information content** at each level: docstrings on the class describe the abstraction; method comments describe the per-call contract; in-line comments describe non-obvious implementation. Don't repeat across levels.

- **Diagnostic:** "If I deleted the comment, what would a caller misuse?" That's the load-bearing content. Anything else is noise.
- **Most common mistake:** comments that paraphrase the code (`# increment counter` above `counter += 1`). They add tokens, not abstraction. The actual interface contract — "this method is not idempotent; calling it twice double-counts" — is the missing thing.

---

## Cross-cutting heuristics for a coordinator-style refactor

Where a class wires Provider + Context + ToolRunner + persistence + a sub-pipeline, the highest-leverage PoSD lenses are:

1. **Pass-through audit** — every method on the coordinator that just forwards is a depth-loss. Either inline or abstract upward.
2. **Pass-through variable audit** — IDs/handles that travel through three layers untouched are leakage. Push them into a context object owned at the layer that uses them.
3. **Different-abstraction check between coordinator and collaborators** — if the coordinator's vocabulary is the union of its collaborators', it isn't a layer, it's a switchboard.
4. **Configuration-parameter audit** — every constructor argument is a candidate "the module didn't want to decide." Default it, compute it, or move it down.
5. **Temporal-decomposition check on the master loop** — pre-tool / call-tool / post-tool stages sharing the same scratchpad shape is leakage; the shape is a design decision and belongs in one place.
6. **Errors-out audit** — each error type the coordinator translates between layers is a candidate for "redefine so this isn't an error here."

## Sources

- [Ousterhout, CS 190 — Modular Design lecture notes (Stanford)](https://web.stanford.edu/~ouster/cgi-bin/cs190-winter18/lecture.php?topic=modularDesign) — primary source for definitions of interface, abstraction, deep/shallow, classitis, pull-complexity-downward, somewhat-general-purpose, different layer different abstraction.
- [Ousterhout, CS 190 — Book Review lecture (Winter 2021)](https://web.stanford.edu/~ouster/cgi-bin/cs190-winter21/lecture.php?topic=bookReview) — chapter map.
- *A Philosophy of Software Design*, 1st ed., 2018 — chapter structure and definitions (TOC: Ch. 4 Modules Should Be Deep, Ch. 5 Information Hiding (and Leakage), Ch. 6 General-Purpose Modules are Deeper, Ch. 7 Different Layer Different Abstraction, Ch. 8 Pull Complexity Downwards, Ch. 9 Better Together Or Better Apart?, Ch. 10 Define Errors Out Of Existence, Ch. 13 Comments).
- [Sébastien Portebois — Software Design Red Flags (notes on PoSD)](https://notes.portebois.net/2021/03/04/13.html) — verbatim red-flag definitions (pass-through methods, naming, interface contamination).
- [TCL Wiki — Define Errors Out of Existence](https://wiki.tcl-lang.org/page/Define+Errors+Out+of+Existence) — `unset` and `substring` examples.
- [Marco Bacis — PoSD summary](https://marcobacis.dev/blog/philosophy-of-software-design/) — temporal decomposition framing.
 