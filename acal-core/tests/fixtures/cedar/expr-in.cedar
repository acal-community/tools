// Expression-position `in` — the general form tinytodo relies on (`principal in
// resource.readers`), plus a bare-Var and a Set-of-entities right operand.
permit (principal, action, resource)
when {
    principal in resource.readers ||
    principal in Team::"admins" ||
    principal in [Team::"a", Team::"b"] ||
    principal in resource
};
