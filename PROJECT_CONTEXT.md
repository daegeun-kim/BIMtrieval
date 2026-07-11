# BIM IFC to PostgreSQL and RAG Project Context

## Project Goal

Build an initial BIM question-answering prototype before fixing a narrower final project topic.

The prototype should:

1. Load high-quality IFC models.
2. Extract IFC data into PostgreSQL.
3. Store semantic embeddings using pgvector.
4. Connect an LLM to both SQL querying and vector retrieval.
5. Test how well the system answers BIM-related questions.
6. Use the findings to define a more specific project direction later.

This is not a machine-learning training project, so a large IFC dataset is not required. A few high-quality IFC models are sufficient.

## Initial Data Scope

Start with approximately 3 to 5 good IFC models.

Prioritize models with:

- Multiple building storeys
- IfcSpace entities
- Walls, doors, windows, slabs, and other common components
- Spatial containment relationships
- Property sets
- Quantities
- Materials and types
- Usable geometry
- Consistent naming and classifications

For the first prototype, the architectural `.ifc` file alone is enough. Additional RVT, PDF, CSV, BCF, structural, or MEP files are optional.

## Suggested IFC Sources

Potential sources include:

- Schependomlaan dataset
- BIMData R&D IFC collection
- Open IFC Model Repository
- STEP Tools IFC sample files
- buildingSMART Sample-Test-Files

Suggested initial models:

- AC20-Institute-Var-2.ifc
- Schependomlaan.ifc
- Trapelo_IFC4_ARC.ifc or NBU_OfficeBuilding_ARC.ifc

## IFC File Structure

An IFC file is usually a STEP-format text file.

Example:

```text
#425=IFCCARTESIANPOINT((-20396.234375,7461.5400390625,11176.375));
```

Meaning:

- `#425` is a local STEP entity ID inside the file.
- `IFCCARTESIANPOINT` is the IFC entity type.
- The numeric values are coordinates for one point.
- It is not the complete geometry of a BIM element.

The IFC file is not stored as a visibly nested tree. It is a graph of entities connected through `#number` references.

Important relationship types include:

- `IfcRelAggregates`
- `IfcRelContainedInSpatialStructure`
- `IfcRelDefinesByProperties`
- `IfcRelAssociatesMaterial`
- `IfcRelSpaceBoundary`

The project hierarchy and element relationships must be reconstructed by following these references.

## IFC Processing

Use Python and IfcOpenShell.

IfcOpenShell should handle:

- Opening IFC files
- Reading entity types
- Extracting GlobalIds
- Extracting names and descriptions
- Extracting storeys and spaces
- Extracting property sets
- Extracting quantities
- Extracting materials
- Extracting types
- Traversing spatial containment
- Traversing element relationships
- Extracting or deriving geometry

The raw IFC file should remain the authoritative source.

## Database Strategy

Use the existing local PostgreSQL database.

Use both:

- PostGIS for spatial geometry
- pgvector for embedding storage and similarity search

Enable extensions:

```sql
CREATE EXTENSION postgis;
CREATE EXTENSION vector;
```

A separate vector-database service is not required for the initial prototype.

## Structured Database

The structured PostgreSQL schema should store exact IFC facts used for filtering, counting, aggregation, and calculations.

Possible tables:

```text
projects
buildings
storeys
spaces
elements
element_properties
element_quantities
element_materials
element_types
element_relationships
space_boundaries
rag_documents
```

Example `elements` fields:

```text
id
project_id
global_id
ifc_class
name
description
object_type
storey_id
space_id
geometry
properties_json
quantities_json
```

SQL should be used for exact questions such as:

- How many doors are in the building?
- How many doors are on 2F?
- Which rooms are larger than 50 square metres?
- What is the total wall area on 3F?
- Which doors have a missing fire rating?

Example:

```sql
SELECT COUNT(*)
FROM elements
WHERE ifc_class = 'IfcDoor';
```

The LLM should preferably call constrained backend tools instead of writing arbitrary SQL.

Example tool call:

```json
{
  "operation": "count_elements",
  "ifc_class": "IfcDoor",
  "storey": null
}
```

The backend generates and executes the SQL.

## RAG and Vector Retrieval

RAG is not a replacement for SQL.

RAG should be used for semantic retrieval and ambiguity, such as:

- Which elements relate to fire separation?
- What components are associated with circulation?
- What is considered part of the service core?
- Which spaces appear related to mechanical service?

SQL should be used for exact and exhaustive operations.

Vector search usually returns the top-k most semantically similar records. It is not reliable for counting every matching item.

The combined system should support:

```text
User question
→ LLM interprets intent
→ choose SQL, vector retrieval, or both
→ retrieve or calculate result
→ LLM explains result
```

## Embedding Strategy

Do not automatically convert every SQL row directly into a vector.

First decide what each vector should represent.

Initial strategy:

- Start with one element-description vector per selected BIM element.
- Generate readable text from structured element data.
- Embed that text.
- Store the vector in `rag_documents`.
- Link the vector record back to the source element using its database ID or IFC GlobalId.

Example element text:

```text
IfcDoor D-201 is located on Level 2. It connects Corridor 201 to Stair 2.
It has a 60-minute fire rating and is 900 millimetres wide.
Its IFC GlobalId is 2YtK7F8ab9.
```

Suggested `rag_documents` structure:

```text
id
project_id
source_entity_id
document_type
content
embedding
metadata_json
```

One SQL row does not have to equal one vector.

Possible future vector types:

- Element-description vectors
- Space-summary vectors
- Storey-summary vectors
- Type-description vectors
- Material-description vectors
- Spatial-relationship vectors
- Building-level summary vectors
- Project terminology vectors

Additional embedding types can be added later.

## SQL and Vector Relationship

Use one PostgreSQL database with separate relational and vector-enabled tables.

Example:

```text
PostgreSQL
├── structured IFC tables
└── rag_documents with pgvector embeddings
```

The usual workflow should be:

```text
IFC
→ parse with IfcOpenShell
→ store normalized structured data in PostgreSQL
→ generate selected text documents from structured records
→ generate embeddings
→ store embeddings with pgvector
```

## LLM Knowledge of IFC Classes

The LLM should not be expected to guess database fields or IFC classes.

Provide it with:

- Allowed tool definitions
- Database schema
- Supported IFC classes
- Mapping dictionaries
- Project terminology
- Optional RAG-retrieved schema context

Example mapping:

```text
door → IfcDoor
wall → IfcWall
window → IfcWindow
room or space → IfcSpace
floor or level → IfcBuildingStorey
```

Use constrained tool arguments where possible.

Example:

```text
count_elements(
    ifc_class: Literal["IfcDoor", "IfcWall", "IfcWindow"],
    storey: str | None
)
```

## Analytical Questions

Questions involving geometry, ratios, distances, connectivity, or simulation require dedicated functions, not only RAG.

Examples:

- Core area divided by total floor area
- Exterior-facing wall ratio
- Isoperimetric quotient
- Egress distance
- Space connectivity
- Clash detection
- Daylight performance

Example:

```text
What is the core-to-floor-area ratio on 2F?
```

Required process:

```text
LLM interprets the requested metric
→ identifies 2F and the core definition
→ calls a deterministic calculation function
→ function queries all relevant spaces and areas
→ function calculates the ratio
→ LLM explains the result
```

RAG may retrieve the definition of "core," but the calculation must be deterministic.

## Initial Prototype Scope

The first version should support:

1. IFC file ingestion
2. IFC parsing with IfcOpenShell
3. PostgreSQL storage
4. Basic element, property, quantity, and storey extraction
5. pgvector installation
6. Element-description generation
7. Embedding generation
8. Vector similarity search
9. Exact SQL-based counting and filtering
10. LLM tool routing between SQL and vector retrieval
11. Answers referencing IFC GlobalIds and source elements

Initial test questions:

```text
How many doors are in the building?
How many doors are on 2F?
What wall types are used?
Which doors have fire-rating information?
Which components relate to fire safety?
Describe the elements in a selected room.
Which properties are missing from the doors?
```

## Recommended Technology Stack

```text
Language: Python
IFC parser: IfcOpenShell
Database: PostgreSQL
Spatial extension: PostGIS
Vector extension: pgvector
LLM integration: direct tool calling, LlamaIndex, or LangChain
Backend: FastAPI
Prototype interface: Streamlit
Optional IFC viewer: IFC.js, Bonsai, BIMvision, or BIMcollab Zoom
```

For the first implementation, avoid adding a separate vector database such as Qdrant, Pinecone, Weaviate, or Milvus.

## Development Order

```text
1. Download 3 to 5 IFC files.
2. Inspect them visually in an IFC viewer.
3. Inspect their entities using IfcOpenShell.
4. Design the minimum PostgreSQL schema.
5. Import IFC entities and relationships.
6. Validate imported counts and properties.
7. Install and enable pgvector.
8. Generate element-description documents.
9. Generate and store embeddings.
10. Implement SQL query tools.
11. Implement vector retrieval.
12. Connect both retrieval methods to the LLM.
13. Test questions and document failures.
14. Decide the final narrower BIM project direction.
```

## Current Key Decision

Start with element-description embeddings only.

Do not attempt to support every possible BIM question at the beginning. Add new SQL fields, relationships, geometry functions, and vector document types only when required by the later project direction.
