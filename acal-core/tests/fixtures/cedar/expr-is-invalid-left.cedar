// `X is Type` where X is not principal/action/resource directly — same boundary as
// expr-in-invalid-left.cedar: entity-type is only defined for the request's own variables.
permit (principal, action, resource)
when { resource.owner is User };
