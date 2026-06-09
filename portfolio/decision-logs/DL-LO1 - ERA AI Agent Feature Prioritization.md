Decision Log Entry [LO1]

#0. Context: Why does this question exist?

Project/assignment this belongs to: ERA AI Agent

Why this matters right now:
Before writing a single line of code, I needed to decide what to build and in what order. The law firm had broad needs, conversational legal help, document analysis, contract drafting, client offers, and a way to manage the firm's track record. Building everything at once was not realistic for a solo developer with a live stakeholder expecting usable output at each step. Getting the sequence wrong would mean delivering features nobody could use yet, or blocking later features with earlier architectural choices that did not account for them.

Where this fits: See @ERA AI Agent Development Plan for the full phased roadmap this decision produced.

#1. My research question

How should the ERA AI Agent feature set be structured and sequenced so that each phase delivers something immediately usable to the firm, while keeping the architecture open for the features that follow?

#2. Current LO stage

Analysing

#3. What makes a good decision here?

My criteria for success:

*Each phase delivers at least one feature the firm partner can use without any further development work. A phase that produces only infrastructure with no visible output is not a valid phase.
*No phase should require throwing away or significantly refactoring the previous phase's code to add the next feature. Architectural compatibility across phases is a binary: either the next feature fits the existing shape or it does not.
*The sequence must match the firm's actual urgency. The most frequently needed tool comes first, not the technically easiest one.
*Each phase must be deployable and testable on the live Railway environment before the next phase begins. "Works on my machine" does not count as a phase completion.

#4. What I decided

Structure the build as five sequential phases: Phase 1 as a bilingual legal chat assistant, Phase 2 as document analysis (PDF and DOCX upload), Phase 3 as contract and invoice drafting, Phase 4 as client offer and general description generation, and Phase 5 as a self-service content management layer for the firm's track record. Each phase ships to the live deployment before the next begins.

#5. Why this decision

Method I used:
I mapped the firm's workflow end to end, from first client contact to document delivery, and identified which tasks the partner spent the most time on and which involved the most repetitive work. I then cross-checked that sequence against architectural dependencies: which features needed which infrastructure to already exist.

What I found and observed:

*The partner's most frequent need was quick legal and research answers, often while on calls or between meetings. A chat assistant with no document features is immediately useful from day one. This made chat the correct Phase 1 rather than something more technically complex.
*Document analysis came second because the partner regularly received contracts and legal documents from counterparties and needed a fast way to get a summary and extract key clauses. This required the Python backend and the Anthropic API, which were already in place from Phase 1, so it added capability without adding infrastructure.
*Contract and invoice drafting came third because it depended on the document ingestion and generation stack that Phase 2 established. Reversing the order would have required building generation before ingestion, which is a harder start.
*Client offer and general description generation came fourth. These are higher-effort documents produced less frequently than contracts, but they are high-value outputs for business development. They also introduced the PPTX generation path, which required python-pptx and the template-fill architecture, and those are cleanest to introduce after the simpler DOCX generation is stable.
*The self-service content layer (Phase 5) came last because it depends on the full document suite existing first. Editing a project list that feeds into documents only makes sense once those documents are live.

Links to evidence and artifacts:

*Phase sequencing is recorded in @ERA AI Agent Development Plan.
*Phase 1 completion: commit 944d63f ("first prototype deployed for testing") in @GitHub Repository ERA AI Agent.
*Phase 2 completion: commit d4d7400 ("analyze feature implemented") in @GitHub Repository ERA AI Agent.
*Phase 3 completion: commit 67a59eb ("contract drafting feature V1") in @GitHub Repository ERA AI Agent.
*Phase 4 completion: commits 4dfb65f and 31d4581 in @GitHub Repository ERA AI Agent.
*Phase 5 completion: commits 8d4a794, 0d0aa51, and 56904ef in @GitHub Repository ERA AI Agent.

What this means:
The sequence is not arbitrary. Each phase unlocks the infrastructure the next one needs, and each phase delivers something the partner can use before the next one starts. Reversing any adjacent pair breaks either the dependency chain or the usefulness criterion.

So I decided:
The five-phase sequence above satisfies all four criteria. Every phase has a live deployment milestone (criterion 4), every phase output is immediately usable (criterion 1), no phase required discarding the previous architecture (criterion 2), and the order matches the firm's stated workflow priorities (criterion 3).

#6. Does this hold up?

How well this meets my criteria:

*Criterion 1, each phase usable on delivery: Met. Each commit marked as a phase completion in the log above corresponds to a deployed feature the partner tested. The earliest, commit 944d63f, is the first prototype the partner used to validate the approach.
*Criterion 2, no architectural throwaway between phases: Met. The Python FastAPI backend introduced in Phase 2 is the same backend serving all subsequent phases. The template-fill pattern introduced in Phase 3 (DOCX) extended cleanly to Phase 4 (PPTX) without refactoring. See `PY/era_agent/pipelines/` in @GitHub Repository ERA AI Agent for all pipeline modules sharing the same structure.
*Criterion 3, sequence matches firm urgency: Met. The partner confirmed after Phase 1 that the chat assistant was already saving time on research queries. Phases 3 and 4 addressed the document production workload the partner described as the next bottleneck.
*Criterion 4, each phase deployable before the next: Met. The Railway deployment was live from Phase 1 onward, verifiable at @Railway Hosting - ERA AI Agent.

Assumptions I am making:
I assumed the partner's priorities would remain stable enough that the sequence would not need to be completely reordered mid-project. I checked this by reviewing the feedback captured in @ERA AI Agent Development Plan after each phase. What I found was that the priorities held: no phase was skipped or reordered based on stakeholder feedback. The residual risk is that a significant external event (for example, a regulatory change requiring a specific new document type urgently) could reorder future phases, but that is managed through the iterative review after each delivery rather than upfront.

What surprised me:
The self-service content layer (Phase 5) was not in the original plan at that level of detail. It emerged from a direct stakeholder request during Phase 4: the partner asked whether he could update the firm's project list himself rather than asking me to do it each time. That request confirmed the phasing was working as intended. The partner was engaged enough with the tool to want ownership of it, which is only possible because the earlier phases had made it genuinely useful.

#7. What this unlocks

Links to implementation evidence:

*The full pipeline suite is visible in `PY/era_agent/pipelines/` in @GitHub Repository ERA AI Agent, with one module per document type, each following the same structure introduced in Phase 3.
*The live application at @Railway Hosting - ERA AI Agent shows all five phases deployed and accessible.
*The self-service dashboard (Phase 5) is visible in `ERA AI/Pages/Dashboard.cshtml` in @GitHub Repository ERA AI Agent.

Next LO stage: Advising, Designing

What I can now do that I could not before:
I can add a new document type to the ERA AI Agent by adding one pipeline module, one API endpoint, and one UI tab, without touching any other feature. The phased architecture makes extension safe and predictable.

How I will know this worked:
The partner uses a different feature in each session without needing to ask what is available. Each phase's output is part of a regular workflow rather than a demonstration that gets used once. The self-service dashboard being used to add a new project without any developer intervention is the clearest confirmation that the sequence delivered what it was designed to.
