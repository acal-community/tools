// Expression-position `is` (Cedar 4.x), bare and combined with `in` — as tinytodo's
// templated policy set uses (`resource is List && resource.owner == principal`).
permit (principal, action, resource)
when { resource is List && resource.owner == principal };

permit (principal, action, resource)
when { resource is List in Application::"Demo" };
