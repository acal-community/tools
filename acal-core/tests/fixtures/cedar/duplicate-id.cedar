// Two policies with the same @id — ACAL rule ids must be unique within a policy.
@id("shared")
permit (principal, action, resource) when { principal.a == 1 };
@id("shared")
forbid (principal, action, resource) when { resource.b == 2 };
