// Multi-level attribute/record access (`a.b.c`, and bracket-index `a["k"]`, which the EST
// represents identically) flattens into one compound dotted AttributeId, as sales_orgs and
// streaming_service rely on. Also exercises chained `has` and a chain used as an `in` target.
permit (principal, action, resource)
when {
    principal.subscription.tier == "premium" &&
    principal.roles["admin"] has enabled &&
    principal in resource.owner.team
};
