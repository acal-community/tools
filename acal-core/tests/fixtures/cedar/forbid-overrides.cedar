// A permit and a forbid: proves the outer/inner combining nest.
permit (principal, action, resource) when { principal.active == true };
forbid (principal, action, resource) when { resource.classification == "secret" };
