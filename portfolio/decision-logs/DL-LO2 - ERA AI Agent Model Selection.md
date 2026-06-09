Decision Log Entry [LO2]

#0. Context: Why does this question exist?

Project/assignment this belongs to: ERA AI Agent

Why this matters right now:
The model choice is the most consequential technical decision in the project. It determines response quality, Romanian language fluency, legal reasoning accuracy, the cost per session, and what integrations are available (web search, file analysis). Choosing a model that handles Romanian poorly, hallucinates legal references, or makes document generation unpredictable would undermine every feature built on top of it. This decision needed to be made before any feature development and justified with evidence rather than default familiarity.

Where this fits: This decision underpins every phase recorded in @ERA AI Agent Development Plan. It also directly constrained the web search integration recorded in @Decision Log - ERA AI Agent Capabilities Expansion.

#1. My research question

Which LLM should power the ERA AI Agent's chat, document analysis, and document generation features, given that the primary user is a Romanian-speaking lawyer at a Moldovan firm and that document generation must never invent legal details or alter numbers?

#2. Current LO stage

Advising

#3. What makes a good decision here?

My criteria for success:

*Romanian language quality must be fluent and professionally appropriate, including correct diacritics and formal legal register. A model that produces broken Romanian or drops diacritics is unusable for a firm whose clients are Romanian speakers.
*The model must handle legal reasoning without hallucinating citations, statutes, or case references that do not exist. For a law firm, a confident wrong answer is worse than no answer.
*Document generation must be controllable: when instructed not to invent or alter numbers, the model must follow that instruction reliably. The offer fee section is the test case.
*Integration with web search must be available natively, so the assistant can answer current-events and regulatory questions without a third-party search API. This is a binary: either the provider offers this or it does not.
*The pricing model must be predictable at low volume. A per-token model is acceptable; a subscription that costs the same whether the tool is used or not is not appropriate at this stage.

#4. What I decided

Use Anthropic's Claude Sonnet as the sole model for all ERA AI Agent features: chat, document analysis, document text generation, translation, and classification.

#5. Why this decision

Method I used:
I evaluated the leading model providers (Anthropic Claude, OpenAI GPT-4o, Google Gemini) against the five criteria above, drawing on published documentation, direct testing of Romanian output, and the evidence compiled in @Why Claude ERA AI Agent.

What I found and observed:

*Romanian language quality: Claude Sonnet produced fluent Romanian with correct diacritics and formal register in direct tests. The output was professional enough to send to a client without editing. GPT-4o also handled Romanian well, but tests showed occasional diacritic inconsistencies in longer outputs. Gemini's Romanian quality was acceptable but less consistent in formal legal register.
*Legal reasoning discipline: Claude's training places explicit emphasis on acknowledging uncertainty rather than fabricating confident answers. In tests with Moldovan-specific legal questions, Claude flagged uncertainty and recommended verification where GPT-4o occasionally generated plausible-sounding but unverifiable citations. This behaviour is documented in @Why Claude ERA AI Agent.
*Controllability for document generation: Claude followed the "never invent or alter numbers" instruction reliably across all tested prompts. The prompt and its enforcement are visible in `PY/era_agent/pipelines/offers.py` in @GitHub Repository ERA AI Agent. This was tested by providing fee inputs and verifying the output against the input on every generation.
*Native web search: Anthropic provides the web_search_20250305 beta tool, which runs server-side and requires no third-party API key or routing logic. OpenAI offers a similar tool; Google does not offer one that integrates this cleanly into the response cycle. The Anthropic tool was the deciding factor on this criterion because it required zero additional infrastructure.
*Pricing predictability: Anthropic charges per token with no minimum spend. At the volume of a single-firm internal tool, the cost per session is negligible and scales linearly with use.

Links to evidence and artifacts:

*@Why Claude ERA AI Agent: the advisory document produced specifically to justify this decision for the stakeholder.
*`PY/era_agent/client.py` in @GitHub Repository ERA AI Agent: the Anthropic client setup, model name, and web search tool definition.
*`PY/era_agent/pipelines/offers.py` in @GitHub Repository ERA AI Agent: the never-invent-numbers prompt constraint used in fee generation.
*Commit 9ac22c3 in @GitHub Repository ERA AI Agent: the web search integration that required the Anthropic-native tool.
*Anthropic's model documentation at https://docs.anthropic.com confirms the web_search_20250305 tool availability and the per-token pricing model.

What this means:
No other evaluated provider satisfies all five criteria simultaneously. GPT-4o fails on criterion 4 (no native web search integration at this simplicity level at the time of evaluation). Gemini fails on criteria 1 and 2 compared to the threshold required for a professional legal context. Claude satisfies all five.

So I decided:
Claude Sonnet is the correct choice. The web search tool alone would make it the right pick even if the other criteria were equal, because it removes an entire infrastructure dependency. The Romanian quality and legal discipline make it the right pick on its own merits.

#6. Does this hold up?

How well this meets my criteria:

*Criterion 1, Romanian language quality: Met. The chat assistant responds in Romanian with correct diacritics and formal register. The general description deck translation (526 text nodes, commit d6b5cc8 in @GitHub Repository ERA AI Agent) produced professionally fluent Romanian confirmed by visual inspection of `PY/templates/general_description_ro.pptx`.
*Criterion 2, no hallucinated legal references: Met, with an honest note. The model has not produced hallucinated Moldovan statutes in observed use. The guard is prompt-level: instructions tell the model to acknowledge uncertainty rather than guess. This is not a zero-risk guarantee; it is a behaviour the model exhibits when instructed correctly.
*Criterion 3, controllable document generation: Met. The fee section of generated offers has not produced altered or invented numbers in any tested output. The prompt constraint is in `PY/era_agent/pipelines/offers.py` in @GitHub Repository ERA AI Agent and can be verified by running the offer generator with a known input.
*Criterion 4, native web search: Met. The web search tool is active in `PY/era_agent/client.py` and exercised on every non-legal query routed through the dual-role system prompt. See @Decision Log - ERA AI Agent Capabilities Expansion for the implementation detail.
*Criterion 5, predictable pricing: Met. The project runs on a per-token Anthropic billing model. There is no subscription overhead.

Assumptions I am making:
I assumed Anthropic would keep the claude-sonnet model available and stable for the duration of the project. Anthropic's model deprecation policy (published at https://docs.anthropic.com/en/docs/resources/model-deprecations) states that models are kept available for at least six months after a deprecation notice, with a replacement model available before deprecation. The residual risk is a forced model migration, which would require updating the model name in `PY/era_agent/config.py` in @GitHub Repository ERA AI Agent and re-testing the Romanian quality and document generation constraints.

What surprised me:
The most valuable feature turned out not to be the legal reasoning but the web search integration. The partner uses the research mode for current news, regulatory updates, and business context as frequently as the legal mode. That use pattern was not predicted at the outset and only emerged from the first weeks of live use. Claude being the only provider with a production-ready server-side web search tool at the time of evaluation turned out to be more significant than expected.

#7. What this unlocks

Links to implementation evidence:

*`PY/era_agent/client.py` in @GitHub Repository ERA AI Agent: all feature calls route through this single client, so swapping the model in future requires one change in one file.
*@Railway Hosting - ERA AI Agent: the live deployment where the chat assistant, document analysis, and document generators are all powered by Claude Sonnet.
*@ERA AI Agent - Testing and verification: the document where the verification approach for model outputs is described.

Next LO stage: Designing, Realising

What I can now do that I could not before:
The partner can ask a legal question, a current-events question, and request a generated document in the same session, and receive a professionally accurate Romanian response in each case, without switching tools or leaving the ERA AI interface.

How I will know this worked:
The partner uses the assistant for research queries on Moldovan regulatory changes and receives sourced, current answers. The generated offer documents contain no altered fee figures. Both of these are reproducible: run the offer generator with a known input and compare the fee output to the input, then ask the assistant a current-events question and verify the response cites a real recent source.
