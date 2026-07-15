// Exercises has, contains/Any/All, like, arithmetic, comparison, set literal.
permit (principal, action, resource)
when {
  principal has email
  && resource.tags.contains("public")
  && resource.tags.containsAny(["a", "b"])
  && resource.tags.containsAll(["a"])
  && principal.name like "dr_*"
  && principal.age >= 18
  && principal.level + 1 > 2
};
