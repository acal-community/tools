// Exercises all three scope operators (in / == / is) and a when clause.
@id("doctors-read-records")
permit (
  principal in Group::"doctors",
  action == Action::"read",
  resource is MedicalRecord
)
when { principal.role == "doctor" }
unless { resource.sealed == true };
