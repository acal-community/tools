// A template with a principal slot — becomes a parameterized ACAL Policy.
permit (principal == ?principal, action, resource)
when { context.mfa == true };
