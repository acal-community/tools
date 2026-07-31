# Proposal: `MetadataType` — a place for facts a PDP must ignore

**Status:** proposed, not adopted.
**Affects:** ACAL 1.0 core, all three serializations.
**Discussion:** [acal-community/tools#12](https://github.com/acal-community/tools/issues/12)

This directory is both the proposal and the thing that runs. The four schema fragments
beside this file are applied by `yacal-validate --proposal metadata` and
`jacal-validate --proposal metadata`, so what the TC reviews and what the working
demonstration validates against are the same bytes. They cannot drift.

---

## The problem

ACAL 1.0 has nowhere to record a structured fact *about* a document that is not part of
the policy the document expresses.

The concrete case is conversion. Importing from a spoke language loses information, and
that loss has to be recorded somewhere the document carries with it — a report printed
beside the file is discarded by the first person who redirects stdout. But the need is not
specific to conversion: policy author, creation and modification timestamps, and
deployment tags are the same shape of fact, and implementations are keeping them today
with no sanctioned home.

Two existing properties look like they would serve, and neither does.

**`PolicyIssuer` is disqualified by its own normative text.** A PDP that does not implement
the Administration and Delegation profile MUST report an error or return `Indeterminate`
when it encounters the object (§7.4). That obligation attaches to the property being
*populated*, not to what is inside it — so a document annotated this way stops evaluating
on any PDP without the profile. `PolicyIssuer` also already means something: it identifies
who issued the policy for delegation trust chains. A policy legitimately setting its own
issuer would have no way to keep that separate from injected annotation in the same
`Attribute` array.

**`Description` is a comment.** It is `[0..1] String` with no structure, and nothing may be
parsed out of it without inventing a private encoding. Using it for structured facts
produces exactly the unstructured mess it looks like it would.

What is missing is not a place to put things. It is a property with an explicit
**MUST-ignore** rule. ACAL 1.0 has no such rule anywhere: `Description` is silent on
evaluation, and `PolicyIssuer` carries the opposite rule.

---

## The proposal

### `MetadataType`

```
class MetadataType {
  + Attribute: AttributeType [*] {unique by (AttributeId, Issuer)}
  + Content:   ContentType   [0..1]
}
note "{{OCL} Content <> null or Attribute->notEmpty()}" as non_empty_constraint
MetadataType .. non_empty_constraint
```

Deliberately the shape of `EntityType` — the type `PolicyIssuer` already uses — down to the
non-empty guard. That is the whole point of the design: **no serialization gains new
grammar.** Every implementation that can read an `EntityType` can read a `MetadataType`,
and all three serializations already express `{Attribute: [...], Content: {...}}`
identically.

There is no third state. A `Metadata` property is either absent or has content; the
non-empty constraint exists so a tool cannot emit `Metadata: {}` to say "I was here."

### Normative text

> A `Metadata` property is non-normative. Its content **MUST NOT** affect policy
> evaluation, and a PDP encountering a `Metadata` property **MUST** evaluate the enclosing
> object exactly as if the property were absent.

This sentence is the proposal. The container is ordinary; the MUST-ignore rule is what
does not exist today and what makes the container safe to write into.

### Attachment points

| Type | |
|---|---|
| `PolicyType` | The unit an annotation is usually about. |
| `BundleType` | Origin is a fact about the document, not about any policy inside it. Stamping each contained `PolicyType` is redundant, and becomes actively wrong once two bundles of different origin are merged. `BundleType` also has no `Description`, so it has no annotation route at all today. |

That is the entire required ask: **two types, one new type definition, one sentence of
normative text.** See [Deliberately not asked for](#deliberately-not-asked-for) below for
what was considered and dropped, and why the list is this short.

### Identifier namespace

Facts go in `AttributeId`, in namespaces. The conversion case uses
`urn:oasis:names:tc:acal:1.0:provenance:*`:

| `AttributeId` | Example value |
|---|---|
| `…:provenance:source-language` | `alfa` |
| `…:provenance:source-dialect` | `xacml-3.0` |
| `…:provenance:tool` | `acal-convert/0.2.0` |
| `…:provenance:fidelity` | `lossless` \| `lossy` |
| `…:provenance:conversion-report` | a JSON array of notes, as a string |

Provenance is **not a type and not a property name** — it is a namespace inside a generic
container. Author, timestamps and tags share the container under their own namespaces.
That genericity is why the type is called `MetadataType` and not `ProvenanceType`.

---

## Decisions, and what they cost

### `Content` is permitted by the type and unused by the profile

`MetadataType` keeps `Content: ContentType [0..1]` for `EntityType` parity, but a
provenance profile **SHOULD** use only `Attribute`.

Support for `ContentType` is optional in ACAL (§7.34 — required only for implementations
supporting `AttributeSelector`/`DataType` extensions that depend on it), and the JSON
schema tells implementers outright that they may delete the subschema. Annotation that
lived in `Content` would depend on a feature implementations are explicitly invited to
remove, and it would be the first use of `Content` unrelated to attribute selectors.

### No new `DataType`

The conversion report is a JSON array carried as a string at the default
`urn:oasis:names:tc:acal:1.0:data-type:string` (§7.27). The `AttributeId` defines the
format by convention.

Minting a datatype identifier would pull an inert blob into the type system, where
datatypes carry equality and matching functions and take part in designator and selector
resolution — none of which a blob wants. A consumer dispatches on the `AttributeId` it
already had to recognise; nothing needs the datatype to know what it is holding.

Tooling that wants a machine-visible hint can carry a sibling attribute rather than a new
datatype.

### Uniqueness is by `(AttributeId, Issuer)`

This amends the `isUnique(AttributeId)` shape first proposed in discussion.

`AttributeType` carries an `Issuer`, and two attributes sharing an `AttributeId` while
differing in `Issuer` are meaningful everywhere else the type appears. A metadata
container has no reason to be the one place that is forbidden — an author stamp from two
issuers is a realistic document, and keying on `AttributeId` alone rejects it.

The rule lives in the constraint catalog rather than in any structural schema, because
none of the three can express it: JSON Schema 2020-12 has no uniqueness-by-key (the
published schema already records this as a TODO on `EntityType.Attribute`), and XSD's
`xs:unique` skips any tuple with an absent field — which is every `Attribute` that omits
`Issuer`, i.e. almost all of them.

### `Metadata.Attribute[*]` reuses `AttributeType` unchanged

Whether the items should be closed (`unevaluatedProperties: false`) or left open was
flagged in discussion as needing a conscious decision rather than inheritance.

The decision is to reuse `AttributeType` verbatim and inherit its openness. A container
defined by a MUST-ignore rule has no business being stricter than the type it borrows: an
unrecognised key inside an object a PDP is already required to ignore cannot change any
evaluation outcome, so rejecting the document over it buys nothing and forecloses
extension.

---

## Deliberately not asked for

Four things were on the table during discussion and are not in this proposal. Each was
dropped for a reason, and the reasons are worth as much as the proposal.

### A `…:metadata:description` attribute — **withdrawn**

The idea was a standard `AttributeId` for descriptions, giving `BundleType` and the
`ShortId` types (which have no `Description` property) a route to one.

It is withdrawn. `Description` is a comment, not authoritative of anything — so declaring
it "authoritative" over a metadata attribute states a precedence between two things that
never conflict in any way an implementation could act on. And if the metadata attribute
*did* become authoritative for some external tool, then it is emphatically not
interchangeable with `Description`, and the precedence rule is wrong in the other
direction.

Two mechanisms for one concept with no defensible precedence rule is worse than one
mechanism with a gap. All existing `Description` properties stay exactly as they are, and
this proposal defines no `urn:oasis:names:tc:acal:1.0:metadata:*` namespace at all.

### `Metadata` on `ShortIdType` — **not pursued**

An ALFA attribute declaration carries four facts:

```alfa
attribute docPath {
  id       = "urn:example:doc-path"
  category = resourceCat
  type     = string
}
```

`ShortIdType` is `Name` → `Value`, which holds the alias and the URI. `category` and `type`
have nowhere to go, and the obvious fix is `Metadata` on `ShortIdType`.

Not pursued, for two reasons. The mechanical one: `ShortIdType` is attribute-only in the
XSD, so gaining a child element converts it from an empty complexType into one with a
content model — a larger change than it looks, in the type with the most instances per
document. The structural one: it would put the same fact in two places, since a converter
must stamp `category` and datatype onto every referencing `AttributeDesignator` regardless.

The case is solved instead **inside `Metadata` on the policy**, by carrying the source
language's symbol table as one JSON attribute in a tool-owned namespace. That needs
nothing beyond the two attachment points already requested, is inert by construction, and
scales to any declaration kind without further schema change — where a per-`ShortId`
property could only ever describe the aliases `ShortIdSet` already holds.

The reader preserves what its symbol table actually collects today: attribute, obligation
and advice declarations. ALFA's category, type, function and combining-algorithm
declarations are parsed and discarded during collection, so they do not survive — a gap
in the reader, not in the container. Closing it needs no further schema work.
See [`acal-converter/README.md`](../../../acal-converter/README.md) for the emitted shape.

### `SharedVariableDefinition` as a declaration carrier — **rejected**

An alternative for the same ALFA problem: model each attribute declaration as a
`SharedVariableDefinition` whose `Expression` is an `AttributeDesignator` carrying the
category and datatype, with the ALFA short name in the variable `Id`. It needs no schema
change whatsoever, which is a real advantage.

It is rejected because a `SharedVariableDefinition` is normative and evaluable. The
approach fabricates policy content in order to store facts that are not policy: a document
gains N shared variables that the author never wrote, and every attribute reference becomes
a `VariableReference` instead of a designator. A reader cannot afterwards distinguish a
converter-synthesised variable from one the author intended.

That is the same category error as `PolicyIssuer`, one level down — using a construct the
PDP evaluates as a place to keep things the PDP should ignore. The whole purpose of this
proposal is to stop doing that.

### `Metadata` on `ShortIdSetType` and `SharedVariableDefinitionType` — **not required**

Both were proposed in discussion and both are reasonable; a per-definition author or
timestamp is a coherent thing to want.

They are held back only because no implemented use case needs them once the ALFA case
moves to document-level `Metadata`, and a two-type ask is easier to evaluate than a
five-type one. Nothing in this proposal precludes them, and adding them later is additive
in all three serializations — the fragments here would extend by two entries each.

`RuleType` is deferred on the same basis; it is needed only for per-rule fidelity, which
nothing produces today.

---

## Files in this directory

| File | Applies to |
|---|---|
| [`yaml.fragment.yaml`](yaml.fragment.yaml) | YACAL structure schema |
| [`json.fragment.json`](json.fragment.json) | JACAL JSON Schema |
| [`xsd.fragment.xsd`](xsd.fragment.xsd) | XACML 4.0 XML Schema |
| [`constraints.fragment.yaml`](constraints.fragment.yaml) | Core constraint catalog |

Each fragment has two parts: a `$defs` (or element/complexType) section adding
`MetadataType`, and a `PropertyAdditions` section naming the existing types that gain a
`Metadata` property. The split is deliberate — a fragment never restates a host type it
does not own, because a copy of a published definition living in this repository would go
stale the first time the published one moved.

Beyond these, adoption would need the `MetadataType` definition and the MUST-ignore
sentence in the normative core specification, plus updated examples.

One incidental finding while building the fragments, offered as an observation rather than
part of the proposal: in the published schemas `PolicyType` is closed
(`additionalProperties: false`) in both the YACAL and JACAL structure schemas, but
`BundleType` is closed only in YACAL. A JACAL bundle therefore already accepts unknown
properties today, `Metadata` among them. Whichever way the TC resolves that, the two
serializations should presumably agree.

## Trying it

```bash
acal-convert policy.alfa --to yacal --provenance -o policy.yaml

yacal-validate policy.yaml                       # fails: Metadata is not admitted today
yacal-validate --proposal metadata policy.yaml   # passes, and says which proposal it applied
```

The validator names every applied proposal in its output. A run with `--proposal` is not a
conformance result and does not read as one.
