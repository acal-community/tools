// `action in [Entity, Entity]` — the multi-entity form of scope `in`. Distinct from the
// single-entity form already covered by entity-scope.cedar: this is a disjunction over
// every listed entity, not a single string-is-in check.
permit (
    principal,
    action in [Action::"Read", Action::"Write"],
    resource == Application::"Demo"
);
