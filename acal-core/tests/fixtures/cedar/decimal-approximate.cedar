// decimal is fixed-point; ACAL double is IEEE-754 — approximate, warns.
permit (principal, action, resource)
when { principal.balance.greaterThan(decimal("100.0")) };
