// Integer literals/sets must produce integer-typed ACAL functions, not string-typed.
permit (principal, action, resource)
when {
  principal.age == 21
  && resource.levels.contains(3)
  && resource.levels.containsAll([1, 2])
};
