// A Cedar @id that is not a legal ACAL LocalIdentifierType (colons, not letter-led here it is,
// but colons are illegal in a Rule Id). Must be sanitized to a valid id and reported.
@id("urn:acme:policy:read")
permit (principal, action, resource) when { principal.ok == true };
