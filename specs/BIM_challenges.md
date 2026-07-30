# Main Role:

- BIM Manager: Defines the templates, standards, families, and workflows that govern how the BIM model is created and maintained.
- Project Architect: Uses the BIM model to make and coordinate architectural, technical, and code-related design decisions.
- Job Captain / Architectural Staff: Develop the BIM model in detail and produce drawings, schedules, renderings, and other deliverables from it.
- BIM Coordinator: Monitors model quality, manages consultant-model coordination, and resolves project-level BIM technical issues.
- Project Manager: Manages the schedule, budget, staffing, and client communication that guide the BIM-based project process.

# Communication Issue Analysis and Example

BIM communication problems usually occur when team members treat the model as a single source of truth, but do not share the same understanding of:

what information the model contains;
how reliable each element is;
what the model may be used for;
who is responsible for correcting or approving it.

Research based on three real BIM projects examined more than 2,000 model-compliance issues and found recurring information problems involving incomplete, inaccurate, inconsistent, redundant, poorly structured, or difficult-to-understand information.

Common communication challenges
1. Different interpretations of model completeness

The Project Architect may consider a wall, ceiling, or equipment object sufficiently developed for design coordination. The BIM Coordinator may consider the same object incomplete because it lacks accurate dimensions, materials, classification, clearance zones, or other required data.

This creates conversations such as:

Architect: “The design is still developing.”
BIM Coordinator: “The model does not meet the required LOD.”
Job Captain: “Which elements must we complete for this submission?”
Project Manager: “Why is the BIM deliverable late?”

LOD is intended to communicate how reliable model elements are and what downstream users can reasonably do with them. Without clearly defined LOD requirements, visible geometry can appear much more certain than it actually is.

2. The model looks complete but contains incomplete information

A BIM model may visually resemble a finished building while containing:

generic wall and door types;
placeholder equipment;
approximate ceiling heights;
unconfirmed structural openings;
missing fire ratings;
missing parameters;
2D details that do not correspond to the 3D model.

This creates false confidence. The Project Manager or client may think the design is finalized because the model looks detailed, while the architect understands that many elements are provisional.

Research identifies incomplete, inaccurate, inconsistent, and unintelligible information as major reasons BIM models become unreliable for later users.

3. Outdated models and conflicting sources

The architectural team may update the Revit model, but consultants may still be working from:

an earlier uploaded model;
a previous PDF set;
exported CAD backgrounds;
an old federated coordination model.

A construction practitioner described receiving early architectural models that were not subsequently updated, while later drawings contained different information. The result was that consultants and contractors were coordinating against conflicting versions of the project. This is anecdotal rather than a formally documented case, but it closely reflects a common version-control failure.

The communication problem becomes: Which version is authoritative—the live model, published model, PDF set, or coordination export?

4. Poor BIM standards make information difficult to interpret

Problems arise when teams use inconsistent:

family and type names;
parameters;
classification systems;
coordinates and levels;
worksets;
file names;
room and equipment identifiers;
model-sharing procedures.

The BIM Coordinator may understand that two elements are technically different, but the Project Architect or Project Manager may see identical-looking objects. Conversely, an architect may understand the design difference, but the model may not encode that difference clearly enough for schedules, clash detection, or consultant use.

Practitioners also describe models assembled from manufacturer families, CAD imports, legacy schedules, and inconsistent templates. Such models may produce drawings but become difficult to audit, coordinate, or exchange.

5. Unclear responsibility for BIM issues

A clash report may identify a duct intersecting a beam and ceiling, but the model does not determine who must resolve it.

Possible questions include:

Does the architect lower the ceiling?
Does the mechanical engineer reroute the duct?
Does the structural engineer modify the beam?
Does the BIM Coordinator merely record the problem or propose the solution?
Who approves the final change?

Practitioners repeatedly identify unclear coordination responsibility and the absence of an enforced BIM Execution Plan as major causes of unresolved coordination issues.

The BIM Coordinator can identify and communicate the clash, but normally cannot independently make architectural or engineering decisions.

6. Different technical knowledge among roles

The Project Architect may understand the design but not recognize the consequences of changing a level, coordinate system, host relationship, family, or model origin.

The BIM Technician may understand Revit deeply but lack authority to resolve the underlying architectural question.

The Project Manager may understand the client, scope, and schedule but rely primarily on drawings and reports rather than inspecting the model directly.

One practitioner described managers who reviewed printed drawings but did not understand how schedules, equipment, and information were structured inside Revit. Another described project managers promising highly coordinated models without providing more time than a conventional CAD project.

This produces a translation burden for the Job Captain and BIM Coordinator, who must explain technical model conditions in terms of design, cost, scope, and schedule.

7. Model complexity generates communication noise

Large models can produce hundreds or thousands of:

clashes;
warnings;
missing parameters;
duplicate objects;
minor geometric intersections;
outdated links;
unresolved issue markers.

Not every issue matters equally. A BIM Coordinator may report 1,000 clashes, while the Project Architect needs to know which 20 affect design or construction. Without prioritization, the quantity of model information can make communication less effective rather than more effective.

Actual practitioner-reported case: Architect–BIM Coordinator LOD conflict

A newly appointed BIM Coordinator described an architectural firm where architects modeled most elements around LOD 100–200, with some elements at LOD 300. The coordinator wanted substantially more elements developed to LOD 300–400 and interpreted the existing model as insufficiently detailed.

An architect and BIM manager responding to the case explained that the disagreement was not simply about modeling quality. Higher development would require:

additional architectural decisions;
more staff and production time;
additional computing and model-management resources;
greater responsibility for the accuracy of modeled elements;
a fee and schedule that supported the additional work.
How the communication failure develops
BIM Manager or Coordinator expectation: The model should contain enough information for comprehensive coordination and downstream use.
Project Architect expectation: The model should contain only the information needed for the current design and documentation stage.
Job Captain and BIM Technician experience: They receive requests to “complete the model” without knowing which components require additional development or whether the work is within scope.
Project Manager problem: Additional modeling appears as an unexpected schedule and fee problem.
Client or contractor interpretation: Because the model looks detailed, they may assume every element is accurate and coordinated.

The actual root problem is therefore not that one team member is necessarily wrong. The project failed to establish a shared definition of:

intended BIM uses;
required LOD by element and project stage;
responsible model author;
authorized uses of model information;
required review and approval procedures;
time and fee allocated for model development.