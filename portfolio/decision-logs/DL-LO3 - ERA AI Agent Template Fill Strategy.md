Decision Log Entry [LO3]

#0. Context: Why does this question exist?

Project/assignment this belongs to: ERA AI Agent

Why this matters right now:
The ERA AI Agent needed to produce Word documents and PowerPoint presentations that look identical to what the firm already sends clients. The firm's visual identity is built into their existing templates: specific fonts, layouts, colour schemes, logo placement, table formatting, and slide designs that clients associate with the firm. Any generated document that looks different, even slightly, would undermine the credibility of the tool. Before building any document generator, I had to decide how to produce those outputs.

Where this fits: This decision shapes every document pipeline built in Phases 3 and 4, recorded in @ERA AI Agent Development Plan. The resulting architecture is documented in @ERA AI Agent - System architecture and the implementation detail is in @ERA AI Agent - Implementation report.

#1. My research question

How should ERA AI Agent generate Word documents and PowerPoint presentations so that the output is visually identical to the firm's existing documents, without requiring design work on the developer's part for each new document type?

#2. Current LO stage

Designing

#3. What makes a good decision here?

My criteria for success:

*Generated documents must be visually indistinguishable from the firm's manually produced versions when opened in Word or PowerPoint. This is a binary: either the font, layout, and design match or they do not. A reader who does not know the document was generated should not be able to tell.
*Adding a new document type must not require building a new layout from scratch. The approach must scale to at least four document types (contract, invoice, offer, general description) without proportionally increasing the design effort.
*The approach must not require any design software or manual intervention in the generation loop. The document must be producible by running a function call with text inputs.
*The approach must preserve all formatting even when only a small number of fields are changed per document. A contract where only the client name and date change must still have the correct fonts, paragraph spacing, and section structure throughout.

#4. What I decided

Generate all documents by programmatically filling pre-built, design-approved Office templates. The firm provides existing documents that already embody the correct design. The pipeline opens the template, locates specific text anchors or table cells, replaces only those fields, and saves the result. No layout is constructed in code.

#5. Why this decision

Method I used:
I evaluated two approaches: building documents from scratch using a library (python-docx or pptxgenjs) to construct every element programmatically, versus treating the firm's existing documents as templates and filling only the client-specific fields. I assessed both against the four criteria above.

What I found and observed:

*Building from scratch: produces correct output if every formatting detail is specified in code. For a DOCX contract this means programmatically defining every paragraph style, font, size, spacing, and table border. For the 48-slide general description deck this means constructing every text box, image, background, and section layout. The design effort is proportional to the document complexity and must be repeated for each new document type. Any design change requires a code change.
*Template fill: the firm's existing documents already have the correct design baked in. The only code needed per document type is the logic to locate the fields that change (client name, date, fee amount, addressee block) and replace them while leaving everything else untouched. Design changes are made in the template file, not in code.
*The template-fill approach also handles a specific constraint in the general description deck: the 48-slide PowerPoint has complex slide layouts, logo images, table structures, and Romanian-specific font rendering that would take days to reproduce programmatically. The existing deck, once corrected for a formatting defect in slide 2, is already correct. The correct answer was to fill it, not rebuild it.

Links to evidence and artifacts:

*`PY/templates/` in @GitHub Repository ERA AI Agent: the four template files (contract_client.docx, invoice_client.docx, custom_offer_en.pptx, custom_offer_ro.pptx, general_description_en.pptx, general_description_ro.pptx).
*`PY/era_agent/pipelines/drafting.py`, `invoicing.py`, `offers.py`, and `general_description.py` in @GitHub Repository ERA AI Agent: the four fill pipelines, each following the same locate-and-replace pattern.
*`PY/era_agent/pptx_utils.py` in @GitHub Repository ERA AI Agent: the low-level helpers (set_cell_text, refill_table, clone_slide) that make template fill safe across complex PPTX structures.
*@ERA AI Agent - C4 Diagram (LVL 2): shows the template layer as a component of the Python container.

What this means:
The template-fill approach delegates all design decisions to the firm itself. The firm already knows what their documents should look like because they have been producing them manually for years. The developer's job is to automate the variable parts, not to recreate the fixed parts.

So I decided:
Template fill satisfies all four criteria. Building from scratch fails criterion 2 (proportional design effort per document type) and criterion 4 (formatting preservation without explicit specification). Template fill is not a compromise; it is the architecturally correct choice for a firm with an established visual identity.

#6. Does this hold up?

How well this meets my criteria:

*Criterion 1, visually indistinguishable from manual versions: Met. Generated documents open in Word and PowerPoint with the correct fonts, layouts, and formatting. The slide-2 formatting defect discovered in the general description template (overlapping signature lines caused by a 23% line spacing value left over from a Google Slides export) was identified and corrected before the template was committed, visible in `PY/templates/general_description_en.pptx` in @GitHub Repository ERA AI Agent.
*Criterion 2, adding a new document type without rebuilding a layout: Met. Each of the four document types required writing one pipeline module of roughly 100 to 200 lines. No layout was constructed in code for any of them. The pattern is consistent across all four: open template, locate anchors, replace text, save.
*Criterion 3, no design software or manual intervention in the generation loop: Met. All four generators run as a single function call from the FastAPI endpoint. The output is returned as bytes and downloaded directly by the user. No intermediate manual step is required.
*Criterion 4, formatting preserved across the full document: Met. The pipelines only write to the specific runs and cells they target. All other content, styles, images, and structures in the template remain unchanged. This is verifiable by generating a document with any inputs and opening it in Word or PowerPoint.

Assumptions I am making:
I assumed the firm's existing template files were the authoritative design and that the partner had approved them. I verified this by sharing generated documents with the partner at the end of each phase and incorporating feedback before the next phase. The residual risk is a design change to the firm's identity that would require updating the template files. That update is a one-time file replacement with no code change required, which is the correct behaviour: design changes should be in the design file, not the code.

What surprised me:
The most technically complex part of the template-fill approach was not the DOCX pipelines but the PPTX slide cloning needed for the data-driven experience sections. When project data grows beyond one slide, new slides must be inserted as clones of the template slide, including its image relationships and layout. python-pptx has no built-in slide clone, so this required reimplementing it with correct relationship ID remapping (see `PY/era_agent/pptx_utils.py` in @GitHub Repository ERA AI Agent). That complexity is contained in one utility module and does not affect the template-fill pattern itself.

#7. What this unlocks

Links to implementation evidence:

*`PY/templates/` in @GitHub Repository ERA AI Agent: the live template files that power all four document generators.
*`PY/era_agent/pptx_utils.py` in @GitHub Repository ERA AI Agent: the slide clone utility, verifiable by reading the clone_slide function and its rId remapping logic.
*@Railway Hosting - ERA AI Agent: the live deployment where all four document generators are accessible and produce downloadable outputs.
*@ERA AI Agent - Implementation report: the document describing how the fill logic is structured across all four pipelines.

Next LO stage: Realising

What I can now do that I could not before:
A new document type can be added to the ERA AI Agent by providing the firm's existing template file and writing one pipeline module that locates and replaces the variable fields. No design work is required from the developer and no existing pipeline needs to change.

How I will know this worked:
The partner opens a generated contract, invoice, offer, or general description alongside a manually produced version of the same document type and cannot identify a visual difference. The generated document is ready to send to a client without manual reformatting.
