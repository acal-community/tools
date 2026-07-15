// A template (inert, uninstantiated) alongside an active static policy.
// Output must be a Bundle whose PolicyReference names the active `main` as the
// entry point, with the template sitting inert in the definition pool.
permit (principal == ?principal, action, resource)
when { context.mfa == true };

@id("active")
permit (principal, action, resource)
when { principal.role == "admin" };
