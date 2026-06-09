Decision Log Entry [LO5]

#0. Context: Why does this question exist?

Project/assignment this belongs to: ERA AI Agent

Why this matters right now:
The ERA AI Agent generates documents that showcase the firm's track record: 41 client projects across 15 practice areas. These projects were originally hardcoded into the PowerPoint templates as text inside slides. Every time the firm won a new matter, completed a transaction, or wanted to remove an outdated entry, they would need to contact the developer to edit a slide in a .pptx file and redeploy. That dependency makes the tool fragile and places an unnecessary operational burden on both the developer and the partner. The partner explicitly asked whether he could manage this content himself.

Where this fits: This is a Phase 5 decision in @ERA AI Agent Development Plan. It builds on the hosting and storage infrastructure recorded in @Decision Log - ERA AI Agent Hosting Deployment and the document generation architecture in @ERA AI Agent - System architecture.

#1. My research question

How should the firm's project track record be stored and managed so that the partner can add, edit, and remove entries himself, those changes propagate automatically into all generated documents, and the data is durable across server redeploys?

#2. Current LO stage

Managing

#3. What makes a good decision here?

My criteria for success:

*The partner must be able to add, edit, reorder, and hide project entries without any developer involvement. The threshold is that the partner can do this on a laptop with no technical background, no command-line access, and no knowledge of the codebase.
*Changes must appear in the next generated document immediately after saving. There must be no deployment step between a content edit and its effect on output.
*The stored data must survive a Railway redeploy without any manual backup or restore step. Data loss on a routine deployment is not acceptable for content the partner is actively maintaining.
*The approach must handle content growth without breaking the document layout. If the partner adds ten new M&A projects, the generated slides must accommodate them cleanly, not overflow or truncate.
*Bilingual content must be manageable from a single interface. The same project entry must carry English and Romanian text, and the partner must be able to update both from one place.

#4. What I decided

Extract all project content from the PowerPoint templates into a persistent JSON store on the Railway volume, expose a web-based dashboard within the ERA AI Agent interface for editing, and make the document generators read from the store at generation time rather than from static slide text. Add a per-slide character budget and slide pagination so that content growth produces additional slides rather than overflow.

#5. Why this decision

Method I used:
I evaluated three approaches: keeping content in the slides and providing a manual editing guide, using a hosted database (PostgreSQL or similar), and using a flat JSON file on a persistent volume. I assessed each against the five criteria above.

What I found and observed:

*Keeping content in slides with a manual guide: fails criterion 1 immediately. Editing a PowerPoint slide requires opening the file in PowerPoint, finding the right shape, editing text without breaking formatting, and saving. This is not accessible to a non-technical user and it does not prevent the accidental destruction of slide formatting.
*Hosted database: satisfies criteria 1 through 5 but introduces a dependency on a database service (cost, connection management, schema migrations) that is disproportionate for a dataset of 41 entries that a single user edits occasionally. Railway supports PostgreSQL, but the operational overhead is not justified.
*Flat JSON file on a persistent volume: satisfies all five criteria. The data is human-readable and versionable. Writes are atomic (temp file then replace). A committed seed file bootstraps an empty volume on first deploy so data is never absent. The file is small enough that a full read and write on every save adds no measurable latency.

I also needed to solve the layout growth problem separately. The existing documents had content hardcoded to fit within a fixed number of slides per section. A data-driven generator that just fills in whatever is in the store would overflow slides when the partner adds more projects. The solution was to add a character-budget pagination algorithm that clones the section slide when the budget is exceeded, inserting a (cont.) label on continuation pages. The budget (3200 characters per slide) was calibrated against the original deck's fullest slide to ensure the initial output is identical to the template.

Links to evidence and artifacts:

*`PY/era_agent/content/schema.py` in @GitHub Repository ERA AI Agent: the data model, 15 categories and the bilingual Project record.
*`PY/era_agent/content/store.py` in @GitHub Repository ERA AI Agent: atomic write, timestamped backup on every save, and seed fallback logic.
*`PY/era_agent/content/projects.seed.json` in @GitHub Repository ERA AI Agent: the committed initial dataset of 41 projects extracted from the original templates.
*`PY/era_agent/pipelines/experience.py` in @GitHub Repository ERA AI Agent: the pagination engine, commit 0d0aa51.
*`ERA AI/Pages/Dashboard.cshtml` in @GitHub Repository ERA AI Agent: the self-service editor, commit 56904ef.
*Commit 8d4a794 in @GitHub Repository ERA AI Agent: the data store and seed, deployed without changing any visible output to verify the layer was safe before wiring it to the generators.
*@Decision Log - ERA AI Agent Hosting Deployment: the decision that established the Railway /data volume this store writes to.

What this means:
The flat JSON approach is the right fit for this scale and this user. It keeps the architecture simple, the data portable, and the operational overhead at zero. The pagination engine is what makes it safe for the partner to grow the content without worrying about the output.

So I decided:
JSON store on the Railway volume, web dashboard in the existing interface, data-driven generators with pagination. This satisfies all five criteria and introduces no new infrastructure dependencies.

#6. Does this hold up?

How well this meets my criteria:

*Criterion 1, partner can edit without developer involvement: Met. The dashboard at @Railway Hosting - ERA AI Agent provides add, edit, reorder, hide, and delete for every project entry, with a save button that persists to the store immediately.
*Criterion 2, changes appear in the next generated document: Met. The generators read from the store at call time. There is no cache or build step between a save and the next generation. This is verifiable by editing a project entry in the dashboard, generating a General Description, and confirming the change appears.
*Criterion 3, data survives redeploys: Met. ERA_DATA_DIR points at the Railway /data volume. The store writes there. A redeploy does not touch the volume. On a fresh volume (first deploy), the store falls back to projects.seed.json (commit 8d4a794 in @GitHub Repository ERA AI Agent).
*Criterion 4, content growth does not break layout: Met. The overflow test (20 M&A projects) produced 10 clean paginated slides with correct (cont.) labels and no text overflow. The following section divider appeared correctly after the inserted pages. Reproducible by adding projects to the store and generating a General Description.
*Criterion 5, bilingual content from one interface: Met. Every project card in the dashboard shows English and Romanian fields side by side, with EN-to-RO and RO-to-EN AI translate buttons that call the /translate endpoint.

Assumptions I am making:
I assumed the Railway /data volume persists across plan changes and service restarts. Railway's documentation states volumes persist independently of service lifecycle events. I verified this by deploying a change after the volume was in use and confirming the store data was intact afterward. Residual risk: volume data is not replicated off-platform. The store writes a timestamped backup on every save (visible in `PY/era_agent/content/store.py` in @GitHub Repository ERA AI Agent), but those backups are also on the same volume. An off-volume backup (for example, a periodic copy to a GitHub Gist or object storage) would eliminate this residual risk and is a recorded follow-up.

What surprised me:
The migration step was more complex than expected. The original deck bundled two or three separate client engagements into single table cells in several sections. Separating them required reading the slide XML, identifying the bundled entries, and writing one project record per engagement rather than one per cell. This is recorded as a follow-up in @ERA AI Agent - Implementation report: the seed data is clean but a small number of entries still reflect the original bundled structure and are candidates for splitting when the partner next reviews them.

#7. What this unlocks

Links to implementation evidence:

*The dashboard is live at @Railway Hosting - ERA AI Agent. Navigate to Portofoliu proiecte in the header to reach it.
*`PY/era_agent/content/store.py` in @GitHub Repository ERA AI Agent: the store module with the backup and atomic write logic, verifiable by reading the save_db function.
*`PY/era_agent/pipelines/experience.py` in @GitHub Repository ERA AI Agent: the pagination engine, verifiable by reading the paginate function and the _CHAR_BUDGET constant.
*@ERA AI Agent - Implementation report: the full implementation walkthrough including the migration that seeded the store.

Next LO stage: Analysing (evaluating content quality and partner adoption)

What I can now do that I could not before:
The partner can add a completed transaction to the firm's track record in the dashboard, save it, and generate a General Description that includes it in the correct practice area section, with the correct pagination, in both English and Romanian, without contacting the developer.

How I will know this worked:
The partner adds a new project entry in the dashboard on the live deployment, generates a General Description, and the new entry appears in the correct section with the surrounding formatting intact. A subsequent Railway redeploy leaves the entry in the dashboard unchanged.
