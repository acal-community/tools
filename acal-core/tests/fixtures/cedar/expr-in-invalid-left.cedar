// `X in Y` where X is not principal/action/resource directly. entity-ancestors is only ever
// populated for the request's own four variables, so this has no ACAL mapping and must be a
// named error, not a silent (wrong) translation.
permit (principal, action, resource)
when { resource.owner in Team::"admins" };
