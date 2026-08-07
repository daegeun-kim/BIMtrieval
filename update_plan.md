# BIMtrieval Portfolio Evaluation Extract

## Scope and source

This document extracts and reorganizes only the BIMtrieval-specific content and the portfolio-wide findings that apply to BIMtrieval from `Daegeun_Kim_Portfolio_Evaluation.pdf`. It does not add repository validation, updated findings, interpretation, or inferred tasks.

- Review date: 6 Aug 2026
- Review perspective: senior engineer / hiring manager
- Portfolio reviewed: `github.com/daegeun-kim`, 27 public repositories

## Bottom line

> A genuinely uncommon profile: an architect-trained computational designer who builds real AI systems against AEC-native data formats - IFC, floorplans, parcels, zoning - not generic tutorial projects. Domain depth is the standout asset and is hard to hire for. The gap is software engineering maturity: nothing in the portfolio is deployed, containerized, or CI-gated, and there is no evidence of collaborative development. Hire with confidence into a design-technologist or AEC-vertical AI role at mid level; do not hire into a general software-engineering team expecting production ownership on day one.

Portfolio-level fit scores:

| Role | Score | Assessment |
| --- | ---: | --- |
| Design Technologist (AEC) | 8.5/10 | Strong fit |
| AI Engineer (AEC vertical) | 6.5/10 | Mid-level fit |
| Software Engineer (general product) | 4.5/10 | Weak fit |

## 1. What the portfolio actually contains

### BIMtrieval

| Field | Evaluation |
| --- | --- |
| What it is | IFC building models ingested into PostgreSQL + pgvector; FastAPI read-only query service answering via SQL / graph traversal / RAG / hybrid orchestration; React + Three.js viewer with chat. |
| Stack | Python 3.11, IfcOpenShell, FastAPI, pgvector, Sentence-Transformers, React/TS/Vite/Three.js |
| Grade | **B+** |

### Signal worth naming

> BIMtrieval, neural_floorplan, Explorentory and GeoEstateChat are all independent, self-directed, non-trivial systems - not forks, not tutorials. Four such projects in twelve months is well above what a typical junior-to-mid candidate presents.

## 2. Strengths - a senior engineer's read

### Domain leverage that cannot be taught quickly

> He does not treat buildings as a generic dataset. He parses IFC via IfcOpenShell, models entity/relationship semantics as first-class tables, and understands that BIM questions are simultaneously relational ("how many doors on level 3"), graph-shaped ("what contains this space"), and semantic ("find the fire-rated assemblies"). Most AI engineers entering AEC need six months to learn this. He arrived with it.

### Architectural judgment above his years

> BIMtrieval's design choices are the ones a good staff engineer would make: three applications with PostgreSQL as the sole integration boundary; the backend connects through a dedicated read-only role so it structurally cannot corrupt the model corpus; statement and result limits capped on queries. This is defensive design, and it's deliberate rather than accidental.

### Hybrid retrieval, not naive RAG

> The market is saturated with "embed the docs, call the LLM" projects. BIMtrieval routes across SQL, graph traversal, and vector retrieval, then orchestrates. He also built an explanation panel - surfacing why an answer was produced. That is a product instinct most AI engineers lack.

### Full-stack reach

> Same person: IFC parsing -> Postgres schema design -> embedding generation -> FastAPI service -> React/Three.js 3D viewer -> chat UX. For a design-technologist role, where you're often the entire tooling team, this breadth is the job description.

### Real packaging literacy exists

> mergeprep demonstrates he knows what good looks like: src-layout, Poetry, pytest, GitHub Actions, ReadTheDocs, CHANGELOG, CONTRIBUTING. The knowledge is present - it simply hasn't propagated to the projects that matter most.

### Visible, disciplined AI methodology

> Numbered specs, a task ledger, explicit agent constraints. Covered in Section 6 - it is a differentiator.

## 3. Weaknesses - the same read, unsoftened

### Nothing runs

> This is the single largest problem. GeoEstateChat - his capstone, the flagship of the degree - states in its own README that "the app is not deployable yet due to the database setup." Explorentory requires manual `.env` creation, local database population, a manually started backend, and a separately served frontend. BIMtrieval's documented entry point is `Start BIM RAG.lnk` - a Windows shortcut file committed to git.

> No Dockerfile. No docker-compose. No migrations. No seed script. No hosted demo anywhere in 27 repositories. A hiring manager cannot evaluate what they cannot run, and will not spend 45 minutes provisioning PostGIS to try. The work is better than its accessibility, and that costs him interviews he'd otherwise get.

### No CI on anything that matters

> The only GitHub Actions workflow in the portfolio is in mergeprep - and the tell is that mergeprep ships with `CONDUCT.md`, `CONTRIBUTING.md`, ReadTheDocs config and a src-layout together, which is the exact fingerprint of a packaging-course cookiecutter. So the one repo with CI is plausibly the one where CI came pre-installed. BIMtrieval and neural_floorplan both contain real test suites that nothing automatically runs. Tests that execute only when the author remembers are documentation, not a safety net.

### No evidence of working with other engineers

> Every commit across every repository is solo-authored. No pull requests, no code review, no issue triage, no upstream contributions - despite forking Raster-to-Graph, katrain, and astro-maplibre-template, none of which received a contribution back. Two followers. For a design-technologist role (often a team of one) this barely matters. For a software-engineering role it is a material unknown: we have no data on how he responds to review, negotiates an interface, or maintains code someone else wrote.

### Commit and branch hygiene is coarse

> BIMtrieval is 19 commits for an ingestion pipeline, a query backend, a 3D frontend, and eleven specs. Messages include "Reverting changes", "experiment2 pre-merge satefy backup" (typo shipped), and "Merge experiment1 into experiment2, keeping experiment2 conflict versions" - resolving a merge by wholesale picking one side rather than reconciling it. Each commit is a large, opaque batch. In a team repo this makes review impractical and git bisect useless.

### Repository hygiene lapses that apply to BIMtrieval

> No `.env.example` in projects requiring `OPENAI_API_KEY` and a database URL.

> No screenshots, GIFs, or demo video in any README. For a design technologist, presenting visual work as walls of text is a self-inflicted wound.

### No stated evaluation numbers

> BIMtrieval has `test_query_v1-v3` spec documents and an `evaluation/` module; neural_floorplan trains a segmentation model; street_block_DL logs training history. Not one README reports a metric. No retrieval accuracy, no mIoU, no baseline comparison, no failure analysis. For an AI-engineering role this is the difference between "built a RAG system" and "built a RAG system that answers 78% of dimensional queries correctly, up from 41% with vector-only retrieval." He has the data. He isn't publishing it.

## 4. Where he fits - and where he doesn't

### Good fit: Design Technologist (AEC)

> This is the role the portfolio was, in effect, designed for. The job is to sit between designers and engineering, build internal tooling, automate the tedious, and prototype fast - usually alone or in a two-person team. He brings architecture training, Rhino/Grasshopper-adjacent parametric work, IFC fluency, geospatial analysis, and enough full-stack ability to ship an interface. The absence of CI/CD matters far less here because internal tools live behind the firewall and are judged by whether the design team uses them. He would be productive at a firm like SOM, KPF, Gensler, Arup, Thornton Tomasetti, or a BIM-tooling startup within weeks.

### Conditional fit: AI Engineer (AEC vertical)

> Strong at mid level, at a company whose product touches buildings - BIM/digital-twin platforms, construction tech, proptech, real-estate analytics. He already knows the domain's data model and has built hybrid retrieval end to end, which is genuinely more than most applicants. What he lacks is the production half: evaluation harnesses, cost and latency budgets, retries and failure modes, observability, prompt-versioning, deployment. Hire him onto a team with at least one senior AI/infra engineer to pair with; do not make him the first AI hire responsible for production reliability.

### Poor fit: General Software Engineer

> Against candidates who have shipped services, been on call, reviewed code, and maintained systems they didn't write, this portfolio loses. The evidence gaps are specific and unarguable: no deployment, no containerization, no CI enforcement, no collaborative history, coarse commits, no operational experience. He would likely pass an algorithms screen and struggle in a system-design round the moment it moved to scaling, failure handling, or team workflow. Not a rejection of ability - a statement that the portfolio doesn't yet evidence the specific competencies that role screens for.

### Poor fit: Senior / Lead Anything

> Seniority is measured in judgment under constraints others depend on: mentoring, review, incident response, decisions that survive contact with a team. Every artifact here is solo. He may well have the raw ability - the read-only-role decision and the OLS-over-neural-net decision both suggest it - but there is no evidence of scope beyond himself, and a hiring manager cannot infer it.

### Calibration

> Best read of level: strong mid-level (L3/E3, 2-4 YOE-equivalent) in a vertical AI or design-technology role. In a generalist software organization, junior-to-mid with a steep expected ramp.

## 5. Repository-by-repository: what needs work

### BIMtrieval - strongest concept

#### Weakness it exposes

> Windows-only launcher (`Start BIM RAG.lnk`) as the documented entry point; no `.env.example`; no CI; parallel `CLAUDE.md` and `CODEX.md` that will drift apart; 19 opaque commits.

#### Specific fix, in priority order

> Delete the `.lnk`, replace with a Makefile or compose file. Add `.env.example` and a CI workflow. Consolidate the two agent files into one. Then publish the numbers from `test_query_v1-v3`: accuracy per query type, SQL vs RAG vs hybrid. That table turns a nice project into a portfolio-defining one.

## 6. AI-assisted coding: how well does he use it?

### Done well - genuinely above average

#### He governs the agent instead of improvising with it

> BIMtrieval's `CLAUDE.md` opens with hard scope constraints - operate only within the project root, never touch parent directories, only edit files inside this repo. Most candidates who use AI heavily have no such file at all.

#### Spec-driven, not vibe-driven

> `/specs` holds eleven sequential specifications (`v001_ifc_to_db` -> `v011_component_panel`) plus `BIM_challenges.md` and versioned query-test docs. `/tasks` holds smaller changes. The instruction "Follow specs in /specs. Work one spec version at a time. Do not implement beyond the active spec" is exactly the discipline that separates usable agent output from sprawl. Crucially, the specs are legible design documents in their own right - they'd survive a design review with the AI removed.

#### A real closed-loop ritual

> After each task completes, its markdown is merged into the parent spec and renamed `task01_done.md`. He built himself a lightweight change-management process. That's a systems-thinking instinct.

#### Deliberate blast-radius control

> "All github actions should be done manually by the user. You do not have access." He decided which operations stay human. Also: "Before coding, create a plan. After coding, run tests" and pinned `ruff` format/lint commands.

#### Resource awareness

> He instructs the agent to route work between his CPU and GPU by workload type - practical thinking most people never encode.

#### Cost-disciplined tests

> BIMtrieval's suite is offline by default with zero OpenAI API calls, with live tests separated. That reflects understanding that LLM-dependent tests are slow, flaky, and expensive.

### Done poorly - the pattern is consistent

#### He directs AI well but does not harden its output

> Every weakness in Section 3 is the signature of accepting a working local result and stopping there. The clearest artifact: `Start BIM RAG.lnk` - a Windows shortcut binary, committed, and documented as the way to start the system. An agent asked for "a one-click launcher" on Windows will produce exactly that. A reviewer would have said: this isn't portable, make it a compose file. That review didn't happen.

#### Specs without enforcement

> He wrote "after coding, run tests" - but never built CI to guarantee it. AI-assisted code needs more automated gating than hand-written code, not less, because it arrives faster than a human can carefully read it. He has the tests. He has no gate.

#### Commit shape reveals batch acceptance

> Nineteen commits for a three-application system means large agent-produced changesets landing at once. And "Merge experiment1 into experiment2, keeping experiment2 conflict versions" is resolution by surrender - taking one side wholesale rather than reasoning through the conflict. That's what happens when the author isn't fully resident in the diff.

#### Duplicate agent configs

> `CLAUDE.md` and `CODEX.md` maintained in parallel across two repos will diverge. One canonical file, referenced by both tools, is the maintainable pattern.

#### The last mile is exactly where AI doesn't help unless asked

> Deployment, migrations, seed data, secrets management, observability - the agent will do all of it, but only on request. Two projects that "don't deploy due to database setup" is the fingerprint of never having asked.

### AI-usage verdict

> Direction & process: 8/10. Spec discipline, scoped permissions, and a task ledger put him ahead of most engineers using these tools today - this is a legitimate talking point in an interview.

> Verification & hardening: 4/10. He treats AI as an implementation engine but never as a reviewer, adversary, or ops engineer. The fix is small and entirely learnable: add CI, ask the agent to critique its own output, and demand a deployable artifact as part of "done."

## 7. If he wants the AI-engineer or SWE role - 30 days of work

The following actions from the PDF name BIMtrieval directly or apply to the flagship repositories, including BIMtrieval.

### Action 1

**Action:** `docker compose up` works on BIMtrieval and GeoEstateChat.

**Why it moves the needle:** Converts "interesting claims" into "I ran it in 90 seconds." The highest-leverage change available, by a wide margin.

### Action 2

**Action:** Publish evaluation numbers in BIMtrieval's README.

**Why it moves the needle:** He already ran `test_query_v1-v3`. A table of SQL vs RAG vs hybrid accuracy per query type is the difference between a demo and engineering.

### Action 3

**Action:** Add GitHub Actions running pytest + ruff on the four flagship repos.

**Why it moves the needle:** Directly answers the strongest objection to AI-assisted portfolios. Half a day of work.

### Action 4

**Action:** Screenshots and a 60-second video in every flagship README.

**Why it moves the needle:** Non-negotiable for a design technologist. neural_floorplan's before/after vectorization output should be the first thing anyone sees.

### Action 8

**Action:** Land two upstream PRs - IfcOpenShell, a BIM/geospatial library, or Raster-to-Graph.

**Why it moves the needle:** The only realistic way to produce evidence of code review and collaboration, which is the largest remaining unknown.

## Summary recommendation

> Design Technologist / computational design lead at an AEC firm - advance, strong candidate. The domain-plus-AI combination is scarce and the portfolio directly demonstrates it.

> AI Engineer at a BIM, construction-tech, or proptech company - advance at mid level, paired with a senior engineer, and probe hard on evaluation methodology, cost/latency, and failure handling.

> Generalist Software Engineer - do not advance on portfolio alone. The gap is not intelligence or ambition; it is that six months of shipping and being reviewed hasn't happened yet, and nothing here substitutes for it.

> Trajectory note: the gaps are all mechanical and closable in weeks. The strengths - domain fluency, architectural instinct, honest modeling judgment - are the ones that take years. That asymmetry favors hiring.

## Evaluation basis

> Evaluation based on public repository contents, README documentation, commit history, and portfolio site (`daegeunkim.com`) as of 6 August 2026. Assessment reflects what the public record evidences; private work, professional experience, and interview performance may change these conclusions materially.
